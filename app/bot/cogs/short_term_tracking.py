from __future__ import annotations

import logging

from discord.ext import commands, tasks

from app.bot.cards import build_short_term_tracking_embed
from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.services.short_term_tracking import MarketTrackingService

logger = logging.getLogger(__name__)


class ShortTermTrackingCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: MarketTrackingService,
        guild_id: int,
        poll_seconds: int,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.tracking_loop.change_interval(seconds=poll_seconds)
        self.tracking_loop.start()

    def cog_unload(self) -> None:
        self.tracking_loop.cancel()

    @tasks.loop(seconds=5)
    async def tracking_loop(self) -> None:
        try:
            await self.service.register_missing(self.guild_id)
            if self.service.enabled:
                await self.service.poll(self.guild_id)
            await self._publish_pending_events()
            await report_system_recovery(
                self.bot,
                service="Massive Market Data",
                error_type="SHORT_TERM_TRACKING_FAILED",
                affected="Short-Term automated tracking",
            )
        except Exception as exc:
            logger.warning(
                "event=short_term_tracking_failed error_type=%s",
                type(exc).__name__,
            )
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Massive Market Data",
                error_type="SHORT_TERM_TRACKING_FAILED",
                affected="Short-Term automated tracking",
                detail=type(exc).__name__,
            )

    @tracking_loop.before_loop
    async def before_tracking_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _publish_pending_events(self) -> None:
        while claim := await self.service.next_public_event(self.guild_id):
            channel = self.bot.get_channel(claim.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(claim.channel_id)
            send = getattr(channel, "send", None)
            history = getattr(channel, "history", None)
            if send is None or history is None:
                return
            marker = f"AXIS Short-Term Event · {claim.public_ref}"
            message = None
            async for candidate in history(limit=200):
                if self.bot.user is None or candidate.author.id != self.bot.user.id:
                    continue
                if any(embed.footer.text == marker for embed in candidate.embeds):
                    message = candidate
                    break
            if message is None:
                message = await send(
                    embed=build_short_term_tracking_embed(
                        claim.card,
                        public_ref=claim.public_ref,
                    )
                )
            await self.service.mark_event_published(claim.event_id, message.id)
