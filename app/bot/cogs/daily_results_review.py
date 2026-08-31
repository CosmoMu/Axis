from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal

import discord
from discord.ext import commands, tasks

from app.bot.cards import build_daily_results_snapshot_embed
from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.bot.views.results_review_views import EditCardModal, ResultsReviewView, TradeSelectView
from app.services.daily_results_review import DailyResultsReviewService, ResultsReviewError

logger = logging.getLogger(__name__)


class DailyResultsReviewCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: DailyResultsReviewService,
        guild_id: int,
        manager_role_id: int,
        owner_user_id: int | None,
        draft_delay_minutes: int,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.manager_role_id = manager_role_id
        self.owner_user_id = owner_user_id
        self.draft_delay_minutes = draft_delay_minutes
        self._registered: set[uuid.UUID] = set()
        self.results_loop.start()

    def cog_unload(self) -> None:
        self.results_loop.cancel()

    async def authorize(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        guild = interaction.guild
        allowed = (
            guild is not None
            and guild.id == self.guild_id
            and isinstance(member, discord.Member)
            and (
                member.id in {guild.owner_id, self.owner_user_id}
                or self.manager_role_id in {role.id for role in member.roles}
            )
        )
        if allowed:
            return True
        await self._send_error(interaction, "你没有管理权限。")
        return False

    @tasks.loop(seconds=30)
    async def results_loop(self) -> None:
        try:
            now = datetime.now(UTC)
            ready_date = self.service.draft_ready_date(now, self.draft_delay_minutes)
            if ready_date is not None:
                review = await self.service.prepare_review(self.guild_id, ready_date)
                await self.ensure_review_message(review.id)
            for review_id in await self.service.pending_review_ids(self.guild_id):
                await self.ensure_review_message(review_id)
            if self.bot.user is None:
                return
            for review_id in await self.service.due_review_ids(self.guild_id, now):
                await self._publish(review_id, actor_user_id=self.bot.user.id, scheduled=True)
            await report_system_recovery(
                self.bot,
                service="Daily Results Review",
                error_type="DAILY_RESULTS_REVIEW_FAILED",
                affected="Results Review / Publish",
            )
        except Exception as exc:
            logger.warning("event=daily_results_review_failed error_type=%s", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Daily Results Review",
                error_type="DAILY_RESULTS_REVIEW_FAILED",
                affected="Results Review / Publish",
                detail=type(exc).__name__,
            )

    @results_loop.before_loop
    async def before_results_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def ensure_review_message(self, review_id: uuid.UUID) -> None:
        review = await self.service.get_review(review_id)
        channel = self.bot.get_channel(review.review_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(review.review_channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        history = getattr(channel, "history", None)
        send = getattr(channel, "send", None)
        if fetch_message is None or history is None or send is None:
            raise ResultsReviewError("RESULTS_REVIEW_CHANNEL_NOT_MESSAGEABLE")
        marker = f"AXIS · RESULTS-REVIEW-{review.trading_date:%Y%m%d}"
        message = None
        if review.review_message_id is not None:
            with suppress(discord.NotFound, discord.Forbidden):
                message = await fetch_message(review.review_message_id)
        if message is None:
            async for candidate in history(limit=100):
                if candidate.content == marker:
                    message = candidate
                    break
        view = ResultsReviewView(self, review.id, locked=review.locked)
        if review.id not in self._registered:
            self.bot.add_view(view, message_id=review.review_message_id)
            self._registered.add(review.id)
        embed = build_daily_results_snapshot_embed(review.snapshot, review=True)
        if message is None:
            message = await send(
                content=marker,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.service.attach_review_message(review.id, message.id)
        else:
            await message.edit(embed=embed, view=view)

    async def refresh_review(self, review_id: uuid.UUID) -> None:
        await self.ensure_review_message(review_id)

    async def open_manage(
        self,
        interaction: discord.Interaction,
        review_id: uuid.UUID,
    ) -> None:
        if not await self.authorize(interaction):
            return
        try:
            review = await self.service.get_review(review_id)
            if not review.items:
                await interaction.response.send_message(
                    "当天没有 Eligible Trade。",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "选择一笔订单管理 Include / Exclude、Display 或 Result Correction。",
                view=TradeSelectView(self, review.id, review.items),
                ephemeral=True,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def open_edit_card(
        self,
        interaction: discord.Interaction,
        review_id: uuid.UUID,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.send_modal(EditCardModal(self, review_id))

    async def show_preview(
        self,
        interaction: discord.Interaction,
        review_id: uuid.UUID,
    ) -> None:
        if not await self.authorize(interaction):
            return
        try:
            snapshot = await self.service.current_public_snapshot(review_id)
            await interaction.response.send_message(
                embed=build_daily_results_snapshot_embed(snapshot, review=False),
                ephemeral=True,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def publish_now(
        self,
        interaction: discord.Interaction,
        review_id: uuid.UUID,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self._publish(
                review_id,
                actor_user_id=interaction.user.id,
                scheduled=False,
            )
            await interaction.followup.send("Daily Results 已正式发布。", ephemeral=True)
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def include_item(self, interaction: discord.Interaction, item_id: uuid.UUID) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            review_id = await self.service.set_included(
                item_id,
                included=True,
                actor_user_id=interaction.user.id,
            )
            await self.refresh_review(review_id)
            await interaction.followup.send("Trade 已重新 Included。", ephemeral=True)
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def exclude_item(
        self,
        interaction: discord.Interaction,
        item_id: uuid.UUID,
        reason: str,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            review_id = await self.service.set_included(
                item_id,
                included=False,
                actor_user_id=interaction.user.id,
                reason=reason,
            )
            await self.refresh_review(review_id)
            await interaction.followup.send(
                "Trade 已从当天 Public Results 排除；历史与事件没有删除。",
                ephemeral=True,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def edit_item_display(
        self,
        interaction: discord.Interaction,
        item_id: uuid.UUID,
        display_text: str,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            review_id = await self.service.edit_item_display(
                item_id,
                display_text=display_text,
                actor_user_id=interaction.user.id,
            )
            await self.refresh_review(review_id)
            await interaction.followup.send("Public Display 已更新。", ephemeral=True)
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def edit_card(
        self,
        interaction: discord.Interaction,
        review_id: uuid.UUID,
        *,
        title: str,
        section_order: str,
        footer: str,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.service.edit_card(
                review_id,
                title=title,
                section_order=section_order,
                footer=footer,
                actor_user_id=interaction.user.id,
            )
            await self.refresh_review(review_id)
            await interaction.followup.send("Daily Results Card 已更新。", ephemeral=True)
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def correct_result(
        self,
        interaction: discord.Interaction,
        item_id: uuid.UUID,
        value: Decimal,
        reason: str,
    ) -> None:
        if not await self.authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            review_id = await self.service.correct_result(
                item_id,
                corrected_value=value,
                reason=reason,
                actor_user_id=interaction.user.id,
            )
            await self.refresh_review(review_id)
            review = await self.service.get_review(review_id)
            if review.public_message_id is not None:
                await self.refresh_public(review_id)
            await interaction.followup.send(
                "Result Correction 已保存并写入 Audit。",
                ephemeral=True,
            )
        except Exception as exc:
            await self.handle_error(interaction, exc)

    async def refresh_public(self, review_id: uuid.UUID) -> None:
        review = await self.service.get_review(review_id)
        if review.public_message_id is None:
            return
        channel = self.bot.get_channel(review.public_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(review.public_channel_id)
        message = await channel.fetch_message(review.public_message_id)
        snapshot = await self.service.current_public_snapshot(review_id)
        await message.edit(embed=build_daily_results_snapshot_embed(snapshot, review=False))

    async def _publish(
        self,
        review_id: uuid.UUID,
        *,
        actor_user_id: int,
        scheduled: bool,
    ) -> None:
        claim = await self.service.claim_publish(
            review_id,
            actor_user_id=actor_user_id,
            scheduled=scheduled,
        )
        if not claim.should_publish:
            return
        channel = self.bot.get_channel(claim.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(claim.channel_id)
        marker = f"AXIS · {claim.public_ref}"
        message = None
        async for candidate in channel.history(limit=100):
            if candidate.content == marker:
                message = candidate
                break
        if message is None:
            message = await channel.send(
                content=marker,
                embed=build_daily_results_snapshot_embed(claim.snapshot, review=False),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        await self.service.finalize_publish(
            review_id,
            message_id=message.id,
            actor_user_id=actor_user_id,
        )
        await self.refresh_review(review_id)

    async def handle_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        if isinstance(exc, ResultsReviewError):
            message = f"操作未完成：{exc.code}"
        elif isinstance(exc, discord.HTTPException):
            message = "Discord 操作失败，请稍后重试。"
        else:
            logger.warning(
                "event=results_review_interaction_failed error_type=%s", type(exc).__name__
            )
            message = "操作暂时失败，请稍后重试。"
        await self._send_error(interaction, message)

    @staticmethod
    async def _send_error(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
