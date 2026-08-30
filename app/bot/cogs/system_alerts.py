from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from sqlalchemy import select, text

from app.db.models import LlmInvocation, ScheduledJob, utc_now
from app.domain.enums import JobStatus
from app.services.system_alerts import (
    AlertDecision,
    SystemAlertService,
    SystemAlertSnapshot,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/Toronto")


def _duration(seconds: int) -> str:
    minutes, remaining = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {remaining}s"
    if minutes:
        return f"{minutes}m {remaining}s"
    return f"{remaining}s"


def alert_embed(decision: AlertDecision) -> discord.Embed:
    alert = decision.alert
    recovered = decision.action == "RECOVERY"
    embed = discord.Embed(
        title=("✅ AXIS SYSTEM RECOVERED" if recovered else "🚨 AXIS SYSTEM ALERT"),
        color=0x86F7A8 if recovered else 0xD66A6A,
    )
    embed.add_field(name="Service", value=alert.service, inline=False)
    embed.add_field(
        name="Status",
        value="RECOVERY" if recovered else alert.severity,
        inline=True,
    )
    if alert.affected:
        embed.add_field(name="Affected", value=alert.affected, inline=True)
    if recovered and alert.resolved_at:
        seconds = int((alert.resolved_at - alert.first_seen).total_seconds())
        embed.add_field(name="Downtime", value=_duration(seconds), inline=True)
        embed.add_field(
            name="Recovered",
            value=alert.resolved_at.astimezone(ET).strftime("%H:%M ET"),
            inline=True,
        )
    else:
        embed.add_field(
            name="Started",
            value=alert.first_seen.astimezone(ET).strftime("%H:%M ET"),
            inline=True,
        )
        embed.add_field(name="Error", value=alert.error_type, inline=False)
        if alert.detail:
            embed.add_field(name="Detail", value=alert.detail[:1024], inline=False)
    embed.set_footer(text=f"AXIS System · occurrences {alert.occurrence_count}")
    return embed


class SystemAlertsCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        channel_id: int,
        service: SystemAlertService,
        check_seconds: int,
        moomoo_enabled: bool,
        moomoo_host: str,
        moomoo_port: int,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.service = service
        self.moomoo_enabled = moomoo_enabled
        self.moomoo_host = moomoo_host
        self.moomoo_port = moomoo_port
        self._db_failure_active = False
        self._db_first_seen = None
        self._db_occurrences = 0
        self.health_loop.change_interval(seconds=check_seconds)
        self.health_loop.start()

    def cog_unload(self) -> None:
        self.health_loop.cancel()

    async def report_failure(
        self,
        *,
        severity: str,
        service: str,
        error_type: str,
        affected: str | None = None,
        detail: str | None = None,
    ) -> None:
        try:
            decision = await self.service.report_failure(
                self.guild_id,
                severity=severity,
                service=service,
                error_type=error_type,
                affected=affected,
                detail=detail,
            )
            await self._dispatch(decision)
        except Exception as exc:
            logger.warning("event=system_alert_record_failed error_type=%s", type(exc).__name__)

    async def report_recovery(
        self,
        *,
        service: str,
        error_type: str,
        affected: str | None = None,
    ) -> None:
        try:
            decision = await self.service.report_recovery(
                self.guild_id,
                service=service,
                error_type=error_type,
                affected=affected,
            )
            if decision is not None:
                await self._dispatch(decision)
        except Exception as exc:
            logger.warning("event=system_recovery_record_failed error_type=%s", type(exc).__name__)

    async def _dispatch(self, decision: AlertDecision) -> None:
        if decision.action == "SUPPRESSED":
            return
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(
            self.channel_id
        )
        await channel.send(embed=alert_embed(decision))
        await self.service.mark_notified(decision.alert.id)

    @tasks.loop(seconds=30)
    async def health_loop(self) -> None:
        await self._safe_health_check("database", self._check_database)
        await self._safe_health_check("openai", self._check_openai)
        await self._safe_health_check("scheduled_jobs", self._check_jobs)
        await self._safe_health_check("discord", self._check_discord)
        if self.moomoo_enabled:
            await self._safe_health_check("moomoo", self._check_moomoo)

    async def _safe_health_check(self, name: str, check) -> None:
        try:
            await check()
        except Exception as exc:
            logger.warning(
                "event=health_check_failed check=%s error_type=%s",
                name,
                type(exc).__name__,
            )

    @health_loop.before_loop
    async def before_health_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_database(self) -> None:
        try:
            async with self.service.database.session() as session:
                await session.execute(text("SELECT 1"))
            if self._db_failure_active:
                recorded = await self.service.report_failure(
                    self.guild_id,
                    severity="ERROR",
                    service="Database",
                    error_type="DATABASE_UNAVAILABLE",
                    affected="All AXIS persistence",
                    detail="Database health check failed",
                    first_seen=self._db_first_seen,
                    occurrence_count=max(self._db_occurrences, 1),
                )
                await self.service.mark_notified(recorded.alert.id)
                self._db_failure_active = False
                self._db_first_seen = None
                self._db_occurrences = 0
                await self.report_recovery(
                    service="Database",
                    error_type="DATABASE_UNAVAILABLE",
                    affected="All AXIS persistence",
                )
        except Exception:
            self._db_occurrences += 1
            if not self._db_failure_active:
                self._db_failure_active = True
                self._db_first_seen = utc_now()
                logger.error("event=database_unavailable")
                snapshot = SystemAlertSnapshot(
                    id=uuid.uuid4(),
                    severity="ERROR",
                    service="Database",
                    error_type="DATABASE_UNAVAILABLE",
                    affected="All AXIS persistence",
                    detail="Database health check failed",
                    first_seen=self._db_first_seen,
                    last_seen=self._db_first_seen,
                    occurrence_count=1,
                    resolved_at=None,
                )
                try:
                    channel = self.bot.get_channel(
                        self.channel_id
                    ) or await self.bot.fetch_channel(self.channel_id)
                    await channel.send(embed=alert_embed(AlertDecision("ALERT", snapshot)))
                except Exception as exc:
                    logger.warning(
                        "event=database_alert_dispatch_failed error_type=%s",
                        type(exc).__name__,
                    )

    async def _check_openai(self) -> None:
        cutoff = utc_now() - timedelta(minutes=10)
        async with self.service.database.session() as session:
            latest = await session.scalar(
                select(LlmInvocation)
                .where(LlmInvocation.created_at >= cutoff)
                .order_by(LlmInvocation.created_at.desc())
                .limit(1)
            )
        if latest is None:
            return
        affected = "Signal Parsing / Analysis Parsing"
        if latest.success:
            await self.report_recovery(
                service="OpenAI API",
                error_type="OPENAI_REQUEST_FAILED",
                affected=affected,
            )
        else:
            await self.report_failure(
                severity="ERROR",
                service="OpenAI API",
                error_type="OPENAI_REQUEST_FAILED",
                affected=affected,
                detail=latest.error_type or "Provider request failed",
            )

    async def _check_jobs(self) -> None:
        cutoff = utc_now() - timedelta(minutes=10)
        async with self.service.database.session() as session:
            failed = (
                await session.scalars(
                    select(ScheduledJob).where(
                        ScheduledJob.status == JobStatus.FAILED.value,
                        ScheduledJob.updated_at >= cutoff,
                    )
                )
            ).all()
        groups = {
            "Membership Expiry Job": [job for job in failed if job.job_type == "MEMBERSHIP_EXPIRE"],
            "Backup Job": [job for job in failed if job.job_type == "DATABASE_BACKUP"],
            "Scheduled Jobs": [
                job
                for job in failed
                if job.job_type not in {"MEMBERSHIP_EXPIRE", "DATABASE_BACKUP"}
            ],
        }
        for service_name, jobs in groups.items():
            if jobs:
                await self.report_failure(
                    severity="ERROR",
                    service=service_name,
                    error_type="SCHEDULED_JOB_FAILED",
                    detail=(
                        f"{len(jobs)} failed job(s) in the last 10 minutes: "
                        + ", ".join(sorted({job.job_type for job in jobs}))
                    )[:1000],
                )
            else:
                await self.report_recovery(
                    service=service_name,
                    error_type="SCHEDULED_JOB_FAILED",
                )

    async def _check_discord(self) -> None:
        if self.bot.is_ready() and self.bot.latency < 10:
            await self.report_recovery(
                service="Discord Bot",
                error_type="DISCORD_GATEWAY_DEGRADED",
            )
            return
        await self.report_failure(
            severity="WARNING",
            service="Discord Bot",
            error_type="DISCORD_GATEWAY_DEGRADED",
            affected="Discord interactions and publications",
            detail="Gateway latency exceeded 10 seconds",
        )

    async def _check_moomoo(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.moomoo_host, self.moomoo_port),
                timeout=5,
            )
            writer.close()
            await writer.wait_closed()
            del reader
            await self.report_recovery(
                service="Moomoo OpenD / Quote",
                error_type="MOOMOO_OPEND_UNAVAILABLE",
            )
        except (OSError, TimeoutError):
            await self.report_failure(
                severity="ERROR",
                service="Moomoo OpenD / Quote",
                error_type="MOOMOO_OPEND_UNAVAILABLE",
                affected="Quote snapshots and post-close summaries",
                detail="Local OpenD endpoint is unavailable",
            )


async def report_system_failure(
    bot: commands.Bot,
    *,
    severity: str,
    service: str,
    error_type: str,
    affected: str | None = None,
    detail: str | None = None,
) -> None:
    cog = bot.get_cog("SystemAlertsCog")
    if isinstance(cog, SystemAlertsCog):
        await cog.report_failure(
            severity=severity,
            service=service,
            error_type=error_type,
            affected=affected,
            detail=detail,
        )


async def report_system_recovery(
    bot: commands.Bot,
    *,
    service: str,
    error_type: str,
    affected: str | None = None,
) -> None:
    cog = bot.get_cog("SystemAlertsCog")
    if isinstance(cog, SystemAlertsCog):
        await cog.report_recovery(
            service=service,
            error_type=error_type,
            affected=affected,
        )
