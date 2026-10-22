from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.bot.moomoo_activity_cards import activity_event_embed, daily_summary_embeds
from app.services.daily_summary import scheduled_session_date
from app.services.moomoo_activity import MoomooActivityService
from app.services.trading_calendar import TradingCalendarService

logger = logging.getLogger(__name__)


class MoomooActivityCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: MoomooActivityService,
        guild_id: int,
        channel_id: int,
        reconcile_seconds: int,
        summary_hhmm: str,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.summary_hhmm = summary_hhmm
        self.reconcile_seconds = reconcile_seconds
        self.calendar = TradingCalendarService()
        self._failure_active = False
        self.reconcile_loop.change_interval(seconds=reconcile_seconds)
        self.reconcile_loop.start()
        self.summary_loop.start()

    def cog_unload(self) -> None:
        self.reconcile_loop.cancel()
        self.summary_loop.cancel()

    @tasks.loop(seconds=15)
    async def reconcile_loop(self) -> None:
        try:
            await asyncio.wait_for(
                self.service.reconcile(),
                timeout=max(20, self.reconcile_seconds * 2),
            )
            await asyncio.wait_for(self._dispatch_pending(), timeout=45)
            if self._failure_active:
                with suppress(Exception):
                    await asyncio.wait_for(
                        report_system_recovery(
                            self.bot,
                            service="Moomoo 1K Challenge Mirror",
                            error_type="MOOMOO_ACTIVITY_MIRROR_FAILED",
                            affected="1K challenge read-only synchronization",
                        ),
                        timeout=15,
                    )
                self._failure_active = False
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__))[:200]
            logger.warning("event=moomoo_activity_reconcile_failed code=%s", code)
            if not self._failure_active:
                with suppress(Exception):
                    await asyncio.wait_for(
                        report_system_failure(
                            self.bot,
                            severity="ERROR",
                            service="Moomoo 1K Challenge Mirror",
                            error_type="MOOMOO_ACTIVITY_MIRROR_FAILED",
                            affected="1K challenge read-only synchronization",
                            detail=code,
                        ),
                        timeout=15,
                    )
            self._failure_active = True

    @reconcile_loop.before_loop
    async def before_reconcile_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60)
    async def summary_loop(self) -> None:
        session_date = scheduled_session_date(datetime.now(UTC), self.summary_hhmm)
        if session_date is None or not self.calendar.is_trading_day(session_date):
            return
        try:
            claim = await self.service.prepare_daily_summary(session_date)
            if claim is None:
                return
            channel = await self._channel()
            message_ids = []
            for embed in daily_summary_embeds(claim.snapshot):
                message = await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                message_ids.append(message.id)
            await self.service.mark_summary_published(claim.id, message_ids)
        except Exception as exc:
            logger.warning(
                "event=moomoo_activity_summary_failed error_type=%s", type(exc).__name__
            )
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Moomoo 1K Challenge Mirror",
                error_type="MOOMOO_ACTIVITY_SUMMARY_FAILED",
                affected="1K challenge close summary",
                detail=str(getattr(exc, "code", type(exc).__name__))[:200],
            )

    @summary_loop.before_loop
    async def before_summary_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _channel(self):
        return self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(
            self.channel_id
        )

    async def _dispatch_pending(self) -> None:
        channel = await self._channel()
        for event in await self.service.pending_events():
            embed = activity_event_embed(event)
            message = await self._find_existing_event(channel, embed)
            if message is None:
                message = await asyncio.wait_for(
                    channel.send(
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions.none(),
                    ),
                    timeout=20,
                )
            await asyncio.wait_for(self.service.mark_notified(event), timeout=20)

    async def _find_existing_event(
        self, channel: discord.abc.Messageable, embed: discord.Embed
    ) -> discord.Message | None:
        history = getattr(channel, "history", None)
        if history is None:
            return None
        bot_user = self.bot.user
        async for message in history(limit=100):
            if bot_user is not None and message.author.id != bot_user.id:
                continue
            for candidate in message.embeds:
                if candidate.title != embed.title:
                    continue
                if candidate.timestamp is None or embed.timestamp is None:
                    continue
                if abs((candidate.timestamp - embed.timestamp).total_seconds()) < 1:
                    return message
        return None
