from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from app.bot.cards import (
    build_daily_results_embed,
    build_daily_summary_embeds,
)
from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.services.daily_summary import (
    DailySummaryError,
    DailySummaryService,
    scheduled_session_date,
)
from app.services.short_term_tracking import MarketTrackingService

logger = logging.getLogger(__name__)


class DailySummaryCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: DailySummaryService,
        guild_id: int,
        schedule_hhmm: str,
        tracking_service: MarketTrackingService,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.schedule_hhmm = schedule_hhmm
        self.tracking_service = tracking_service
        self.publish_summaries.start()

    def cog_unload(self) -> None:
        self.publish_summaries.cancel()

    @tasks.loop(seconds=60)
    async def publish_summaries(self) -> None:
        session_date = scheduled_session_date(datetime.now(UTC), self.schedule_hhmm)
        if session_date is None:
            return
        try:
            await self.tracking_service.expire_contracts(self.guild_id)
            ready = await self.service.prepare_session(self.guild_id, session_date)
        except DailySummaryError as exc:
            logger.warning("event=daily_summary_prepare_failed code=%s", exc.code)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Scheduled Jobs",
                error_type="DAILY_SUMMARY_FAILED",
                affected="Post-close summaries",
                detail=exc.code,
            )
            return
        except Exception as exc:
            logger.warning(
                "event=daily_summary_prepare_failed code=UNEXPECTED error_type=%s",
                type(exc).__name__,
            )
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Scheduled Jobs",
                error_type="DAILY_SUMMARY_FAILED",
                affected="Post-close summaries",
                detail=type(exc).__name__,
            )
            return
        await report_system_recovery(
            self.bot,
            service="Scheduled Jobs",
            error_type="DAILY_SUMMARY_FAILED",
            affected="Post-close summaries",
        )
        if not ready:
            return

        for _ in range(2):
            claim = await self.service.next_publishable(self.guild_id, session_date)
            if claim is None:
                break
            try:
                channel = self.bot.get_channel(claim.channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(claim.channel_id)
                existing = await self._find_existing(channel, claim.public_ref)
                if existing is not None:
                    await self.service.finalize(claim.publication_id, existing.id)
                    continue
                send = getattr(channel, "send", None)
                if send is None:
                    raise DailySummaryError("SUMMARY_CHANNEL_NOT_MESSAGEABLE")
                message = await send(
                    content=f"AXIS · {claim.public_ref}",
                    embeds=build_daily_summary_embeds(claim.summary),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await self.service.finalize(claim.publication_id, message.id)
            except DailySummaryError as exc:
                await self.service.mark_failed(claim.publication_id, exc.code)
            except discord.Forbidden:
                await self.service.mark_failed(claim.publication_id, "DISCORD_FORBIDDEN")
            except discord.HTTPException:
                await self.service.mark_failed(claim.publication_id, "DISCORD_HTTP_ERROR")
            except Exception as exc:
                logger.warning(
                    "event=daily_summary_publish_failed error_type=%s",
                    type(exc).__name__,
                )
                await self.service.mark_failed(claim.publication_id, "UNEXPECTED")
        await self._publish_results(session_date)

    @publish_summaries.before_loop
    async def before_publish_summaries(self) -> None:
        await self.bot.wait_until_ready()

    async def _publish_results(self, session_date) -> None:
        claim = await self.service.next_results_publishable(self.guild_id, session_date)
        if claim is None:
            return
        try:
            channel = self.bot.get_channel(claim.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(claim.channel_id)
            existing = await self._find_existing(channel, claim.public_ref)
            if existing is not None:
                await self.service.finalize_results(claim.publication_id, existing.id)
                return
            send = getattr(channel, "send", None)
            if send is None:
                raise DailySummaryError("RESULTS_CHANNEL_NOT_MESSAGEABLE")
            message = await send(
                content=f"AXIS · {claim.public_ref}",
                embed=build_daily_results_embed(claim.card),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.service.finalize_results(claim.publication_id, message.id)
        except DailySummaryError as exc:
            await self.service.mark_results_failed(claim.publication_id, exc.code)
        except discord.Forbidden:
            await self.service.mark_results_failed(claim.publication_id, "DISCORD_FORBIDDEN")
        except discord.HTTPException:
            await self.service.mark_results_failed(claim.publication_id, "DISCORD_HTTP_ERROR")
        except Exception as exc:
            logger.warning("event=daily_results_publish_failed error_type=%s", type(exc).__name__)
            await self.service.mark_results_failed(claim.publication_id, "UNEXPECTED")

    @staticmethod
    async def _find_existing(channel: object, public_ref: str) -> object | None:
        history = getattr(channel, "history", None)
        if history is None:
            return None
        marker = f"AXIS · {public_ref}"
        async for message in history(limit=50):
            if getattr(message, "content", "") == marker:
                return message
        return None
