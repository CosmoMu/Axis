from __future__ import annotations

import logging
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
            await self.service.reconcile()
            await self._dispatch_pending()
            if self._failure_active:
                await report_system_recovery(
                    self.bot,
                    service="Moomoo 1K Challenge Mirror",
                    error_type="MOOMOO_ACTIVITY_MIRROR_FAILED",
                    affected="1K challenge read-only synchronization",
                )
                self._failure_active = False
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__))[:200]
            logger.warning("event=moomoo_activity_reconcile_failed code=%s", code)
            if not self._failure_active:
                await report_system_failure(
                    self.bot,
                    severity="ERROR",
                    service="Moomoo 1K Challenge Mirror",
                    error_type="MOOMOO_ACTIVITY_MIRROR_FAILED",
                    affected="1K challenge read-only synchronization",
                    detail=code,
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
            await channel.send(
                embed=activity_event_embed(event),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.service.mark_notified(event)
