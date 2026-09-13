"""SPY 0DTE diagnostic surface and member five-minute publisher."""

from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.spy_0dte_cards import build_spy_capability_embed, build_spy_snapshot_embed
from app.services.spy_0dte_desk import (
    MoomooSpy0dteProvider,
    Spy0dtePolicy,
    latest_completed_session,
    publishing_slot,
    render_capability_image,
    render_snapshot_image,
)
from app.services.trading_calendar import TradingCalendarService

ET = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


class Spy0dteCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        provider: MoomooSpy0dteProvider,
        policy: Spy0dtePolicy,
        guild_id: int,
        owner_user_id: int,
        card_testing_channel_id: int,
        member_channel_id: int,
        scheduler_enabled: bool,
    ) -> None:
        self.bot = bot
        self.provider = provider
        self.policy = policy
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.card_testing_channel_id = card_testing_channel_id
        self.member_channel_id = member_channel_id
        self.scheduler_enabled = scheduler_enabled
        self.calendar = TradingCalendarService()
        self._published_slots: set[tuple[object, int, int]] = set()
        self._previous_display_score: int | None = None

    async def cog_load(self) -> None:
        if self.scheduler_enabled and self.policy.mode == "MEMBER":
            self.scheduler.start()

    async def cog_unload(self) -> None:
        if self.scheduler.is_running():
            self.scheduler.cancel()

    def _authorized(self, interaction: discord.Interaction) -> bool:
        return bool(
            interaction.guild_id == self.guild_id
            and interaction.channel_id == self.card_testing_channel_id
            and interaction.user.id == self.owner_user_id
            and self.policy.mode == "TEST"
        )

    @app_commands.command(name="test-spy-0dte", description="测试 AXIS SPY 0DTE 数据门禁与卡片")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_spy_0dte(self, interaction: discord.Interaction) -> None:
        if not self._authorized(interaction):
            await interaction.response.send_message(
                "该命令仅限 Owner 在 🧪・卡片测试频道使用。", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        report = await self.provider.probe(latest_completed_session(datetime.now(ET)))
        image = render_capability_image(report, self.policy)
        await interaction.edit_original_response(
            embed=build_spy_capability_embed(report),
            attachments=[discord.File(BytesIO(image), filename="axis-spy-0dte-test.png")],
        )

    @tasks.loop(seconds=30)
    async def scheduler(self) -> None:
        if not self.scheduler_enabled or self.policy.mode != "MEMBER":
            return
        now = datetime.now(ET)
        slot = publishing_slot(now, self.policy, self.calendar)
        if slot is None:
            return
        session_date, slot_hour, slot_minute = slot
        if slot in self._published_slots:
            return
        try:
            channel = self.bot.get_channel(self.member_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.member_channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError("SPY_0DTE_CHANNEL_UNAVAILABLE")
            if await self._already_published(channel, slot):
                self._published_slots.add(slot)
                return
            self._published_slots.add(slot)
            snapshot = await self.provider.snapshot(
                session_date,
                self.policy,
                previous_display_score=self._previous_display_score,
            )
            image = render_snapshot_image(snapshot, self.policy)
            await channel.send(
                embed=build_spy_snapshot_embed(snapshot),
                file=discord.File(BytesIO(image), filename="axis-spy-0dte.png"),
            )
            self._previous_display_score = snapshot.display_score
            logger.info(
                "event=spy_0dte_published session_date=%s slot=%02d:%02d score=%d contracts=%d",
                session_date,
                slot_hour,
                slot_minute,
                snapshot.display_score,
                snapshot.option_contract_count,
            )
        except Exception as exc:
            logger.exception(
                "event=spy_0dte_failed session_date=%s slot=%02d:%02d error_type=%s",
                session_date,
                slot_hour,
                slot_minute,
                getattr(exc, "code", type(exc).__name__),
            )

    async def _already_published(
        self,
        channel: discord.TextChannel,
        slot: tuple[date, int, int],
    ) -> bool:
        """Prevent a service restart from duplicating the current five-minute card."""

        bot_user = self.bot.user
        if bot_user is None:
            return False
        session_date, slot_hour, slot_minute = slot
        async for message in channel.history(limit=10):
            created = message.created_at.astimezone(ET)
            if created.date() < session_date:
                break
            if (
                message.author.id == bot_user.id
                and created.date() == session_date
                and created.hour == slot_hour
                and created.minute == slot_minute
                and any(embed.title == "AXIS · SPY 0DTE" for embed in message.embeds)
            ):
                return True
        return False

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()
