from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from io import BytesIO

import discord
from discord.ext import commands, tasks

from app.bot.cards import (
    build_complete_review_embed,
    build_public_trade_embed,
    build_review_embed,
    build_short_term_entry_embed,
    build_swing_entry_embed,
    build_swing_tracking_embed,
)
from app.bot.ephemeral import ERROR_DELETE_AFTER, send_temporary_ephemeral
from app.bot.views.review_views import (
    ActiveOrdersView,
    PublicationRetryView,
    ReviewDraftView,
)
from app.domain.enums import DraftStatus, TradeCategory
from app.domain.public_cards import (
    PublicTradeCard,
    ShortTermEntryCard,
    SwingTrackedEntryCard,
    SwingTrackingCard,
)
from app.integrations.moomoo_personal_execution import PersonalBrokerError
from app.market_intelligence.trade_plan import (
    SwingLeapsTradePlanService,
    TradePlanArtifact,
)
from app.services.card_review import (
    ACTIVE_REVIEW_STATUSES,
    CardReviewService,
    ReviewConflictError,
    ReviewDraft,
    ReviewError,
    ReviewValidationError,
    missing_field_labels,
    public_preview_payload,
)
from app.services.personal_execution import PersonalExecutionError, PersonalExecutionService
from app.services.short_term_tracking import MarketTrackingService
from app.services.swing_tracking import SIMPLE_TRACKED_SWING, SwingTrackingService
from app.services.trade_publication import (
    PublicationConflictError,
    PublicationError,
    PublicationValidationError,
    TradePublicationService,
)

logger = logging.getLogger(__name__)


def _member_trade_embed_signature(embed: discord.Embed) -> dict[str, object]:
    payload = embed.to_dict()
    payload.pop("footer", None)
    payload.pop("image", None)
    payload.pop("thumbnail", None)
    return payload


def _same_member_trade_embed(existing: discord.Embed, expected: discord.Embed) -> bool:
    """Match a published card without exposing its internal publication reference."""

    title = expected.title or ""
    if title.endswith("STARTER ENTRY") or title.startswith("入场 · "):
        return existing.title == expected.title and existing.description == expected.description
    return _member_trade_embed_signature(existing) == _member_trade_embed_signature(expected)


class CardReviewCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: CardReviewService,
        publication_service: TradePublicationService,
        tracking_service: MarketTrackingService,
        swing_tracking_service: SwingTrackingService,
        trade_plan_service: SwingLeapsTradePlanService | None,
        personal_execution_service: PersonalExecutionService | None,
        guild_id: int,
        channel_id: int,
        manager_role_id: int,
        member_role_id: int,
        owner_user_id: int | None,
    ) -> None:
        self.bot = bot
        self.service = service
        self.publication_service = publication_service
        self.tracking_service = tracking_service
        self.swing_tracking_service = swing_tracking_service
        self.trade_plan_service = trade_plan_service
        self.personal_execution_service = personal_execution_service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.manager_role_id = manager_role_id
        self.member_role_id = member_role_id
        self.owner_user_id = owner_user_id
        self._views_registered = False
        self._review_artifacts: dict[uuid.UUID, tuple[int, TradePlanArtifact]] = {}
        self.review_queue.start()
        self.publication_queue.start()

    def cog_unload(self) -> None:
        self.review_queue.cancel()
        self.publication_queue.cancel()

    async def authorize(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        user = interaction.user
        allowed = (
            guild is not None
            and guild.id == self.guild_id
            and isinstance(user, discord.Member)
            and (
                user.id == guild.owner_id
                or user.id == self.owner_user_id
                or self.manager_role_id in {role.id for role in user.roles}
            )
        )
        if allowed:
            return True
        await send_temporary_ephemeral(
            interaction,
            "你没有操作审核草稿的权限。",
            delete_after=ERROR_DELETE_AFTER,
        )
        return False

    async def authorize_member(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        user = interaction.user
        allowed = (
            guild is not None
            and guild.id == self.guild_id
            and isinstance(user, discord.Member)
            and (
                user.id == guild.owner_id
                or user.id == self.owner_user_id
                or bool(
                    {self.manager_role_id, self.member_role_id} & {role.id for role in user.roles}
                )
            )
        )
        if allowed:
            return True
        await send_temporary_ephemeral(
            interaction,
            "该功能仅对 AXIS 会员开放。",
            delete_after=ERROR_DELETE_AFTER,
        )
        return False

    async def handle_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        if isinstance(exc, ReviewConflictError):
            message = "该草稿已被其他管理员修改，已刷新最新版本。"
            with suppress(Exception):
                draft_id = self._draft_id_from_interaction(interaction)
                await self.refresh(await self.service.get(draft_id))
        elif isinstance(exc, ReviewValidationError):
            if exc.missing_fields:
                message = "无法发布，请先补齐：" + "、".join(
                    missing_field_labels(exc.missing_fields)
                )
            elif exc.code == "CONTRACT_NOT_FOUND":
                message = "Contract not found. 请选择 Expiry，或编辑 Strike / Side。"
            elif exc.code == "OPTION_CHAIN_UNAVAILABLE":
                message = "Option Chain 暂时不可用，尚未保存或发布。"
            else:
                message = f"操作未保存：{exc.code}"
        elif isinstance(exc, PublicationConflictError):
            message = "该订单正在由另一位管理员处理，请稍后重试。"
        elif isinstance(exc, (PublicationValidationError, PublicationError)):
            message = f"发布操作失败：{exc.code}"
        elif isinstance(exc, ReviewError):
            message = f"审核操作失败：{exc.code}"
        else:
            message = "审核操作暂时失败，请重新打开最新草稿。"
        await send_temporary_ephemeral(
            interaction,
            message,
            delete_after=ERROR_DELETE_AFTER,
        )

    @staticmethod
    def _draft_id_from_interaction(interaction: discord.Interaction) -> uuid.UUID:
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        for part in str(custom_id).split(":"):
            if len(part) == 32:
                try:
                    return uuid.UUID(hex=part)
                except ValueError:
                    continue
        raise ReviewError("DRAFT_ID_UNAVAILABLE")

    async def refresh(self, draft: ReviewDraft) -> None:
        if draft.review_message_id is None:
            return
        channel = self.bot.get_channel(draft.review_channel_id or self.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(draft.review_channel_id or self.channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return
        try:
            message = await fetch_message(draft.review_message_id)
            view, _ = await self._edit_review_message(message, draft)
            if view is not None:
                self.bot.add_view(view, message_id=draft.review_message_id)
        except discord.HTTPException:
            return

    @tasks.loop(seconds=5)
    async def review_queue(self) -> None:
        try:
            if not self._views_registered:
                await self._register_views()
                self._views_registered = True
            draft = await self.service.next_unposted(self.guild_id)
            if draft is not None:
                await self._ensure_review_message(draft)
        except Exception as exc:
            logger.warning("event=review_queue_failed error_type=%s", type(exc).__name__)
            return

    @review_queue.before_loop
    async def before_review_queue(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def publication_queue(self) -> None:
        try:
            draft_id = await self.publication_service.next_publishable(self.guild_id)
            if draft_id is None:
                return
            updated = await self.publish_draft(await self.service.get(draft_id))
            await self.refresh(updated)
        except Exception as exc:
            logger.warning("event=publication_queue_failed error_type=%s", type(exc).__name__)
            return

    @publication_queue.before_loop
    async def before_publication_queue(self) -> None:
        await self.bot.wait_until_ready()

    async def _register_views(self) -> None:
        await self._remove_legacy_short_term_buttons()
        for category in (TradeCategory.SWING, TradeCategory.LEAPS):
            self.bot.add_view(ActiveOrdersView(self, category.value))
        for draft in await self.service.registered(self.guild_id):
            with suppress(ReviewError):
                draft = await self.service.ensure_expiry_resolution(draft.id)
            view = await self._review_view(draft)
            if draft.review_message_id is not None and view is not None:
                self.bot.add_view(view, message_id=draft.review_message_id)
                await self.refresh(draft)
        for draft in await self.service.published_without_review_message(self.guild_id):
            await self._ensure_review_message(draft)

    async def _remove_legacy_short_term_buttons(self) -> None:
        targets = await self.publication_service.legacy_short_term_components(self.guild_id)
        for target in targets:
            try:
                channel = self.bot.get_channel(target.channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(target.channel_id)
                fetch_message = getattr(channel, "fetch_message", None)
                if fetch_message is None:
                    continue
                message = await fetch_message(target.message_id)
                await message.edit(view=None)
                await self.publication_service.mark_legacy_component_removed(target.publication_id)
            except discord.HTTPException as exc:
                logger.warning(
                    "event=short_term_legacy_button_cleanup_failed status=%s",
                    exc.status,
                )

    async def _review_view(
        self,
        draft: ReviewDraft,
        *,
        preview_card: PublicTradeCard | None = None,
    ) -> discord.ui.View | None:
        if draft.status in ACTIVE_REVIEW_STATUSES:
            if (draft.selected_category or draft.category_suggestion) == "SHORT_TERM":
                return ReviewDraftView(
                    self,
                    draft,
                    mentor_choices=[],
                    trade_choices=[],
                    preview_card=preview_card,
                )
            if draft.swing_mode == SIMPLE_TRACKED_SWING:
                trade_choices = (
                    await self.service.trade_choices(draft.guild_id, simple_swing_only=True)
                    if draft.action == "CLOSE"
                    else []
                )
                return ReviewDraftView(
                    self,
                    draft,
                    mentor_choices=[],
                    trade_choices=trade_choices,
                    preview_card=preview_card,
                )
            mentor_choices, trade_choices = await asyncio.gather(
                self.service.mentor_choices(draft.guild_id),
                self.service.trade_choices(draft.guild_id),
            )
            return ReviewDraftView(
                self,
                draft,
                mentor_choices=mentor_choices,
                trade_choices=trade_choices,
                preview_card=preview_card,
            )
        if draft.status == DraftStatus.PUBLISH_FAILED.value:
            return PublicationRetryView(self, draft)
        return None

    async def _review_artifact(
        self,
        draft: ReviewDraft,
        *,
        force: bool = False,
    ) -> TradePlanArtifact:
        cache = getattr(self, "_review_artifacts", None)
        if cache is None:
            cache = {}
            self._review_artifacts = cache
        cached = cache.get(draft.id)
        if not force and cached is not None and cached[0] == draft.version:
            return cached[1]
        card = public_preview_payload(draft)
        if self.trade_plan_service is None:
            artifact = TradePlanArtifact(card=card, chart_png=None, provenance={})
        else:
            artifact = await self.trade_plan_service.prepare(card)
        cache[draft.id] = (draft.version, artifact)
        return artifact

    async def _review_presentation(
        self,
        draft: ReviewDraft,
        *,
        force_image: bool = False,
    ) -> tuple[discord.Embed, discord.ui.View | None, bytes | None, str | None]:
        category = draft.selected_category or draft.category_suggestion
        complete_entry = (
            draft.status in ACTIVE_REVIEW_STATUSES
            and category in {TradeCategory.SWING.value, TradeCategory.LEAPS.value}
            and draft.swing_mode != SIMPLE_TRACKED_SWING
            and draft.intent == "NEW_TRADE"
            and draft.action == "ENTRY"
        )
        if not complete_entry:
            return build_review_embed(draft), await self._review_view(draft), None, None
        artifact = await self._review_artifact(draft, force=force_image)
        embed = build_complete_review_embed(draft, artifact.card)
        filename = None
        if artifact.chart_png is not None:
            filename = f"axis-{draft.draft_code.lower()}-v{draft.version}-entry-plan.png"
            embed.set_image(url=f"attachment://{filename}")
        view = await self._review_view(draft, preview_card=artifact.card)
        return embed, view, artifact.chart_png, filename

    async def _edit_review_message(
        self,
        message: discord.Message,
        draft: ReviewDraft,
        *,
        force_image: bool = False,
    ) -> tuple[discord.ui.View | None, bool]:
        embed, view, chart_png, filename = await self._review_presentation(
            draft,
            force_image=force_image,
        )
        if chart_png is not None and filename is not None:
            await message.edit(
                embed=embed,
                attachments=[discord.File(BytesIO(chart_png), filename=filename)],
                view=view,
            )
        else:
            await message.edit(embed=embed, attachments=[], view=view)
        return view, chart_png is not None

    async def regenerate_review_image(self, draft_id: uuid.UUID) -> bool:
        draft = await self.service.get(draft_id)
        if draft.review_message_id is None:
            return False
        channel = self.bot.get_channel(draft.review_channel_id or self.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(draft.review_channel_id or self.channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return False
        message = await fetch_message(draft.review_message_id)
        view, generated = await self._edit_review_message(
            message,
            draft,
            force_image=True,
        )
        if view is not None:
            self.bot.add_view(view, message_id=draft.review_message_id)
        return generated

    async def publish_draft(
        self,
        draft: ReviewDraft,
        *,
        actor_user_id: int | None = None,
        interaction_id: int | None = None,
    ) -> ReviewDraft:
        if (
            draft.selected_category or draft.category_suggestion
        ) == TradeCategory.SHORT_TERM.value and not self.tracking_service.enabled:
            raise PublicationValidationError("SHORT_TERM_TRACKING_DISABLED")
        if (
            getattr(draft, "swing_mode", None) == SIMPLE_TRACKED_SWING
            and draft.action == "ENTRY"
            and not self.swing_tracking_service.enabled
        ):
            raise PublicationValidationError("SWING_TRACKING_DISABLED")
        claim = await self.publication_service.claim(
            draft.id,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
        )
        if claim.already_published or not claim.should_publish:
            return await self.service.get(draft.id)
        if claim.card is None or claim.claim_token is None:
            return await self.service.get(draft.id)

        personal_execution_service = getattr(self, "personal_execution_service", None)
        if personal_execution_service is not None:
            try:
                await personal_execution_service.prepare_publication(
                    claim.publication_id,
                    published_entry=getattr(claim.card, "entry_price", None),
                    actor_user_id=actor_user_id or draft.reviewed_by,
                    force_follow=draft.personal_follow_override,
                )
            except (PersonalExecutionError, PersonalBrokerError) as exc:
                logger.warning("event=personal_execution_publication_failed code=%s", exc.code)
                alerts = self.bot.get_cog("SystemAlertsCog")
                if alerts is not None:
                    await alerts.report_failure(
                        severity="ERROR",
                        service="Moomoo Personal Execution",
                        error_type="PERSONAL_EXECUTION_PUBLICATION_FAILED",
                        affected="Owner-only personal execution; public signal continues",
                        detail=exc.code,
                    )
            except Exception as exc:
                logger.exception(
                    "event=personal_execution_publication_failed error_type=%s",
                    type(exc).__name__,
                )
                alerts = self.bot.get_cog("SystemAlertsCog")
                if alerts is not None:
                    await alerts.report_failure(
                        severity="ERROR",
                        service="Moomoo Personal Execution",
                        error_type="PERSONAL_EXECUTION_PUBLICATION_FAILED",
                        affected="Owner-only personal execution; public signal continues",
                        detail=type(exc).__name__,
                    )
            else:
                alerts = self.bot.get_cog("SystemAlertsCog")
                if alerts is not None:
                    await alerts.report_recovery(
                        service="Moomoo Personal Execution",
                        error_type="PERSONAL_EXECUTION_PUBLICATION_FAILED",
                        affected="Owner-only personal execution; public signal continues",
                    )

        channel = self.bot.get_channel(claim.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(claim.channel_id)
        send = getattr(channel, "send", None)
        history = getattr(channel, "history", None)
        if send is None or history is None:
            await self.publication_service.mark_failed(
                claim.publication_id,
                claim_token=claim.claim_token,
                error_code="DISCORD_CHANNEL_UNAVAILABLE",
            )
            return await self.service.get(draft.id)

        try:
            public_card = claim.card
            chart_png = None
            if isinstance(public_card, PublicTradeCard) and self.trade_plan_service is not None:
                artifact = await self.trade_plan_service.prepare(public_card)
                public_card = artifact.card
                chart_png = artifact.chart_png
            embed = (
                build_short_term_entry_embed(public_card, public_ref=claim.public_ref)
                if isinstance(public_card, ShortTermEntryCard)
                else build_swing_entry_embed(public_card, public_ref=claim.public_ref)
                if isinstance(public_card, SwingTrackedEntryCard)
                else build_swing_tracking_embed(public_card, public_ref=claim.public_ref)
                if isinstance(public_card, SwingTrackingCard)
                else build_public_trade_embed(public_card, public_ref=claim.public_ref)
            )
            filename = None
            if chart_png is not None and isinstance(public_card, PublicTradeCard):
                filename = f"axis-{(public_card.public_trade_id or 'trade').lower()}-entry-plan.png"
                embed.set_image(url=f"attachment://{filename}")

            message = None
            legacy_marker = f"AXIS · {claim.public_ref}"
            async for candidate in history(limit=200):
                if self.bot.user is None or candidate.author.id != self.bot.user.id:
                    continue
                if any(
                    candidate_embed.footer.text == legacy_marker
                    or _same_member_trade_embed(candidate_embed, embed)
                    for candidate_embed in candidate.embeds
                ):
                    message = candidate
                    break
            category = (
                TradeCategory.SHORT_TERM.value
                if isinstance(claim.card, ShortTermEntryCard)
                else TradeCategory.SWING.value
                if isinstance(claim.card, (SwingTrackedEntryCard, SwingTrackingCard))
                else claim.card.category
            )
            view = (
                None
                if category == TradeCategory.SHORT_TERM.value
                else ActiveOrdersView(self, category)
            )
            if message is None:
                if chart_png is not None and filename is not None:
                    message = await send(
                        embed=embed,
                        file=discord.File(BytesIO(chart_png), filename=filename),
                        view=view,
                    )
                else:
                    message = await send(embed=embed, view=view)
            else:
                await message.edit(view=view)
        except discord.HTTPException:
            await self.publication_service.mark_failed(
                claim.publication_id,
                claim_token=claim.claim_token,
                error_code="DISCORD_SEND_FAILED",
            )
            return await self.service.get(draft.id)

        result = await self.publication_service.finalize(
            claim.publication_id,
            claim_token=claim.claim_token,
            message_id=message.id,
        )
        if isinstance(claim.card, ShortTermEntryCard):
            await self.tracking_service.register_trade(result.trade_id, claim.card.entry_price)
        elif isinstance(claim.card, SwingTrackedEntryCard):
            await self.swing_tracking_service.register_trade(
                result.trade_id, claim.card.entry_price
            )
        elif isinstance(claim.card, SwingTrackingCard) and claim.card.card_type == "CLOSE":
            await self.swing_tracking_service.close_trade(
                result.trade_id,
                reference_price=claim.card.price,
                reference_source=(
                    "MANAGER_INPUT" if draft.action_price is not None else "LAST_VALID"
                ),
            )
        return await self.service.get(draft.id)

    async def _ensure_review_message(self, draft: ReviewDraft) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.channel_id)
        send = getattr(channel, "send", None)
        history = getattr(channel, "history", None)
        if send is None or history is None:
            return

        marker = f"AXIS Signal · {draft.draft_code}"
        existing = None
        async for message in history(limit=100):
            if self.bot.user is None or message.author.id != self.bot.user.id:
                continue
            if any(embed.footer.text and marker in embed.footer.text for embed in message.embeds):
                existing = message
                break

        if existing is None:
            embed, view, chart_png, filename = await self._review_presentation(draft)
            if chart_png is not None and filename is not None:
                existing = await send(
                    embed=embed,
                    file=discord.File(BytesIO(chart_png), filename=filename),
                    view=view,
                )
            else:
                existing = await send(embed=embed, view=view)
        else:
            view, _ = await self._edit_review_message(existing, draft)
        saved = await self.service.attach_review_message(
            draft.id,
            channel_id=self.channel_id,
            message_id=existing.id,
        )
        saved_view = await self._review_view(saved)
        if saved_view is not None:
            self.bot.add_view(saved_view, message_id=existing.id)
