from __future__ import annotations

import uuid
from contextlib import suppress

import discord
from discord.ext import commands, tasks

from app.bot.cards import build_review_embed
from app.bot.views.review_views import ReviewDraftView
from app.services.card_review import (
    ACTIVE_REVIEW_STATUSES,
    CardReviewService,
    ReviewConflictError,
    ReviewDraft,
    ReviewError,
    ReviewValidationError,
)


class CardReviewCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: CardReviewService,
        guild_id: int,
        channel_id: int,
        manager_role_id: int,
        owner_user_id: int | None,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.manager_role_id = manager_role_id
        self.owner_user_id = owner_user_id
        self._views_registered = False
        self.review_queue.start()

    def cog_unload(self) -> None:
        self.review_queue.cancel()

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
            view = (
                ReviewDraftView(self, draft)
                if draft.status in ACTIVE_REVIEW_STATUSES
                else None
            )
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
        except Exception:
            return

    @review_queue.before_loop
    async def before_review_queue(self) -> None:
        await self.bot.wait_until_ready()

    async def _register_views(self) -> None:
        for draft in await self.service.registered(self.guild_id):
            if draft.review_message_id is not None and draft.status in ACTIVE_REVIEW_STATUSES:
                self.bot.add_view(
                    ReviewDraftView(self, draft),
                    message_id=draft.review_message_id,
                )

    async def _ensure_review_message(self, draft: ReviewDraft) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.channel_id)
        send = getattr(channel, "send", None)
        history = getattr(channel, "history", None)
        if send is None or history is None:
            return

        marker = f"AXIS Draft ID: {draft.id}"
        existing = None
        async for message in history(limit=100):
            if self.bot.user is None or message.author.id != self.bot.user.id:
                continue
            if any(
                embed.footer.text and marker in embed.footer.text for embed in message.embeds
            ):
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
