from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from app.services.draft_generation import (
    DraftGenerationDisposition,
    DraftGenerationService,
)

logger = logging.getLogger(__name__)


class DraftWorkerCog(commands.Cog):
    def __init__(self, bot: commands.Bot, *, service: DraftGenerationService) -> None:
        self.bot = bot
        self.service = service
        self.process_queue.start()

    def cog_unload(self) -> None:
        self.process_queue.cancel()

    @tasks.loop(seconds=5)
    async def process_queue(self) -> None:
        try:
            result = await self.service.process_next()
        except Exception as exc:
            logger.warning("event=signal_worker_failed error_type=%s", type(exc).__name__)
            return
        if result is None or result.disposition is DraftGenerationDisposition.EXISTING:
            return
        if result.disposition is DraftGenerationDisposition.CREATED:
            content = f"结构化草稿 {result.draft_code} 已生成，等待管理员审核。"
        else:
            content = "信号解析失败，已保存为失败草稿；稍后可重试或手动录入。"
        await self._reply(result.channel_id, result.discord_message_id, content)

    @process_queue.before_loop
    async def before_process_queue(self) -> None:
        await self.bot.wait_until_ready()

    async def _reply(self, channel_id: int, message_id: int, content: str) -> None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return
        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return
        try:
            message = await fetch_message(message_id)
            await message.reply(content, mention_author=False)
        except discord.HTTPException:
            return
