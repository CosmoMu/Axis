from __future__ import annotations

import logging
from datetime import time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from app.bot.personal_execution_cards import (
    event_embed,
    personal_control_embed,
)
from app.bot.views.personal_execution_views import PersonalExecutionControlView
from app.db.models import GuildConfig
from app.services.personal_execution import PersonalExecutionService

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class PersonalExecutionCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        service: PersonalExecutionService,
        guild_id: int,
        channel_id: int,
        owner_user_id: int,
        reconcile_seconds: int,
    ) -> None:
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.owner_user_id = owner_user_id
        self._view = PersonalExecutionControlView(self)
        self._failure_active = False
        self.reconcile_loop.change_interval(seconds=reconcile_seconds)
        self.panel_loop.start()
        self.reconcile_loop.start()
        self.daily_summary_loop.start()

    def cog_unload(self) -> None:
        self.panel_loop.cancel()
        self.reconcile_loop.cancel()
        self.daily_summary_loop.cancel()

    async def authorize(self, interaction: discord.Interaction) -> bool:
        allowed = (
            interaction.guild_id == self.guild_id
            and interaction.user.id == self.owner_user_id
        )
        if not allowed:
            await interaction.response.send_message("Owner only.", ephemeral=True)
        return allowed

    @tasks.loop(seconds=30)
    async def panel_loop(self) -> None:
        try:
            await self.refresh_panel()
        except Exception as exc:
            logger.warning(
                "event=personal_execution_panel_refresh_failed error_type=%s",
                type(exc).__name__,
            )

    @panel_loop.before_loop
    async def before_panel_loop(self) -> None:
        await self.bot.wait_until_ready()
        self.bot.add_view(self._view)
        await self.service.ensure_settings()

    @tasks.loop(seconds=15)
    async def reconcile_loop(self) -> None:
        await self.reconcile_now()

    @reconcile_loop.before_loop
    async def before_reconcile_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=16, minute=15, tzinfo=ET))
    async def daily_summary_loop(self) -> None:
        now = discord.utils.utcnow().astimezone(ET)
        summary_id, snapshot, already_published = await self.service.daily_summary(now.date())
        if already_published:
            return
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(
            self.channel_id
        )
        embed = discord.Embed(title="AXIS PERSONAL EXECUTION · DAILY SUMMARY", color=0x111411)
        embed.description = (
            f"Session {snapshot['session_date']}\n"
            f"Mode {snapshot['execution_mode']}\n"
            f"Fills {snapshot['fills']} · Active {snapshot['active_positions']}\n"
            f"Realized P/L ${snapshot['realized_pnl']}"
        )
        message = await channel.send(embed=embed)
        await self.service.mark_daily_summary_published(summary_id, message.id)

    @daily_summary_loop.before_loop
    async def before_daily_summary_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def reconcile_now(self) -> None:
        try:
            await self.service.reconcile()
            if self._failure_active:
                alerts = self.bot.get_cog("SystemAlertsCog")
                if alerts is not None:
                    await alerts.report_recovery(
                        service="Moomoo Personal Execution",
                        error_type="MOOMOO_PERSONAL_RECONCILIATION_FAILED",
                        affected="Owner-only personal execution",
                    )
                self._failure_active = False
            await self._dispatch_events()
            await self.refresh_panel()
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            if not self._failure_active:
                alerts = self.bot.get_cog("SystemAlertsCog")
                if alerts is not None:
                    await alerts.report_failure(
                        severity="ERROR",
                        service="Moomoo Personal Execution",
                        error_type="MOOMOO_PERSONAL_RECONCILIATION_FAILED",
                        affected="Owner-only personal execution",
                        detail=str(code)[:200],
                    )
            self._failure_active = True
            logger.warning("event=personal_execution_reconcile_failed code=%s", code)

    async def refresh_panel(self) -> None:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(
            self.channel_id
        )
        status = await self.service.status()
        async with self.service.database.session() as session:
            config = await session.get(GuildConfig, self.guild_id)
            if config is None:
                return
            message = None
            if config.moomoo_panel_message_id:
                try:
                    message = await channel.fetch_message(config.moomoo_panel_message_id)
                except discord.HTTPException:
                    message = None
            if message is None:
                message = await channel.send(
                    embed=personal_control_embed(status),
                    view=self._view,
                )
                config.moomoo_panel_message_id = message.id
                await session.commit()
            else:
                await message.edit(embed=personal_control_embed(status), view=self._view)
                self.bot.add_view(self._view, message_id=message.id)

    async def _dispatch_events(self) -> None:
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(
            self.channel_id
        )
        for event in await self.service.pending_events():
            await channel.send(embed=event_embed(event.event_type, event.payload))
            await self.service.mark_event_notified(event.id)
