from __future__ import annotations

import logging
from collections.abc import Iterable

import discord
from discord.ext import commands

from app.services.signal_input import (
    IncomingAttachment,
    IncomingSignal,
    IngestDisposition,
    SignalInputService,
)

logger = logging.getLogger(__name__)


def is_signal_manager(
    *,
    user_id: int,
    role_ids: Iterable[int],
    guild_owner_id: int,
    configured_owner_id: int | None,
    manager_role_id: int,
) -> bool:
    if user_id in (guild_owner_id, configured_owner_id):
        return True
    return manager_role_id in role_ids


class SignalInputCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: SignalInputService,
        guild_id: int,
        channel_id: int,
        manager_role_id: int,
        owner_user_id: int | None,
        draft_processing_enabled: bool,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.manager_role_id = manager_role_id
        self.owner_user_id = owner_user_id
        self.draft_processing_enabled = draft_processing_enabled

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != self.guild_id or message.channel.id != self.channel_id:
            return
        if not isinstance(message.author, discord.Member):
            return

        authorized = is_signal_manager(
            user_id=message.author.id,
            role_ids=(role.id for role in message.author.roles),
            guild_owner_id=message.guild.owner_id,
            configured_owner_id=self.owner_user_id,
            manager_role_id=self.manager_role_id,
        )
        if not authorized:
            await self._safe_reply(message, "你没有提交信号的权限。")
            return

        try:
            result = await self.service.ingest(
                IncomingSignal(
                    guild_id=message.guild.id,
                    message_id=message.id,
                    channel_id=message.channel.id,
                    submitted_by=message.author.id,
                    content=message.content,
                    received_at=message.created_at,
                    attachments=tuple(
                        IncomingAttachment(
                            discord_attachment_id=attachment.id,
                            filename=attachment.filename,
                            content_type=attachment.content_type,
                            size_bytes=attachment.size,
                            read=attachment.read,
                        )
                        for attachment in message.attachments
                    ),
                )
            )
        except Exception as exc:
            logger.warning("event=signal_ingest_failed error_type=%s", type(exc).__name__)
            await self._safe_reply(message, "信号暂时无法保存，请稍后重试。")
            return

        received_response = (
            "已接收信号输入，正在等待解析。"
            if self.draft_processing_enabled
            else "已接收信号输入；LLM 尚未配置，已安全排队。"
        )
        responses = {
            IngestDisposition.RECEIVED: received_response,
            IngestDisposition.DUPLICATE: "这条信号已经接收，无需重复提交。",
            IngestDisposition.REJECTED: (
                "无法接收：请提供文字或 PNG/JPEG/WEBP 图片，单张图片不超过 10MB。"
            ),
            IngestDisposition.FAILED: "信号暂时无法保存，请稍后重试。",
        }
        await self._safe_reply(message, responses[result.disposition])

    @staticmethod
    async def _safe_reply(message: discord.Message, content: str) -> None:
        try:
            await message.reply(content, mention_author=False)
        except discord.HTTPException:
            return
