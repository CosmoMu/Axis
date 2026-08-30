from __future__ import annotations

import logging
import uuid
from contextlib import suppress

import discord
from discord.ext import commands, tasks

from app.bot.cards import build_public_trade_embed, build_review_embed
from app.bot.views.review_views import (
    ActiveOrdersView,
    PublicationRetryView,
    ReviewDraftView,
)
from app.domain.enums import DraftStatus, TradeCategory
from app.services.card_review import (
    ACTIVE_REVIEW_STATUSES,
    CardReviewService,
    ReviewConflictError,
    ReviewDraft,
    ReviewError,
    ReviewValidationError,
)
from app.services.trade_publication import (
    PublicationConflictError,
    PublicationError,
    PublicationValidationError,
    TradePublicationService,
)

logger = logging.getLogger(__name__)


class CardReviewCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: CardReviewService,
        publication_service: TradePublicationService,
        guild_id: int,
        channel_id: int,
        manager_role_id: int,
        member_role_id: int,
        owner_user_id: int | None,
    ) -> None:
        self.bot = bot
        self.service = service
        self.publication_service = publication_service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.manager_role_id = manager_role_id
        self.member_role_id = member_role_id
        self.owner_user_id = owner_user_id
        self._views_registered = False
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
        if not interaction.response.is_done():
            await interaction.response.send_message("你没有操作审核草稿的权限。", ephemeral=True)
        else:
            await interaction.followup.send("你没有操作审核草稿的权限。", ephemeral=True)
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
        await interaction.response.send_message("该功能仅对 AXIS 会员开放。", ephemeral=True)
        return False

    async def handle_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        if isinstance(exc, ReviewConflictError):
            message = "该草稿已被其他管理员修改，已刷新最新版本。"
            with suppress(Exception):
                draft_id = self._draft_id_from_interaction(interaction)
                await self.refresh(await self.service.get(draft_id))
        elif isinstance(exc, ReviewValidationError):
            if exc.missing_fields:
                message = "无法确认，还缺少：" + "、".join(exc.missing_fields)
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
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

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
            view = self._review_view(draft)
            await message.edit(embed=build_review_embed(draft), view=view)
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
        for category in TradeCategory:
            self.bot.add_view(ActiveOrdersView(self, category.value))
        for draft in await self.service.registered(self.guild_id):
            view = self._review_view(draft)
            if draft.review_message_id is not None and view is not None:
                self.bot.add_view(view, message_id=draft.review_message_id)
                await self.refresh(draft)

    def _review_view(self, draft: ReviewDraft) -> discord.ui.View | None:
        if draft.status in ACTIVE_REVIEW_STATUSES:
            return ReviewDraftView(self, draft)
        if draft.status == DraftStatus.PUBLISH_FAILED.value:
            return PublicationRetryView(self, draft)
        return None

    async def publish_draft(
        self,
        draft: ReviewDraft,
        *,
        actor_user_id: int | None = None,
        interaction_id: int | None = None,
    ) -> ReviewDraft:
        claim = await self.publication_service.claim(
            draft.id,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
        )
        if claim.already_published or not claim.should_publish:
            return await self.service.get(draft.id)
        if claim.card is None or claim.claim_token is None:
            return await self.service.get(draft.id)

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

        message = None
        marker = f"AXIS · {claim.public_ref}"
        try:
            async for candidate in history(limit=200):
                if self.bot.user is None or candidate.author.id != self.bot.user.id:
                    continue
                if any(embed.footer.text == marker for embed in candidate.embeds):
                    message = candidate
                    break
            view = ActiveOrdersView(self, claim.card.category)
            if message is None:
                message = await send(
                    embed=build_public_trade_embed(claim.card, public_ref=claim.public_ref),
                    view=view,
                )
            else:
                await message.edit(view=view)
        except discord.HTTPException:
            await self.publication_service.mark_failed(
                claim.publication_id,
                claim_token=claim.claim_token,
                error_code="DISCORD_SEND_FAILED",
            )
            return await self.service.get(draft.id)

        await self.publication_service.finalize(
            claim.publication_id,
            claim_token=claim.claim_token,
            message_id=message.id,
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

        view = ReviewDraftView(self, draft)
        if existing is None:
            existing = await send(embed=build_review_embed(draft), view=view)
        else:
            await existing.edit(embed=build_review_embed(draft), view=view)
        saved = await self.service.attach_review_message(
            draft.id,
            channel_id=self.channel_id,
            message_id=existing.id,
        )
        self.bot.add_view(ReviewDraftView(self, saved), message_id=existing.id)
