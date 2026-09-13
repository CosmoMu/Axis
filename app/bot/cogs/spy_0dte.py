"""Owner-only TEST surface and disabled-by-default scheduler for SPY 0DTE."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.spy_0dte_cards import build_spy_capability_embed
from app.services.spy_0dte_desk import (
    MoomooSpy0dteProvider,
    Spy0dtePolicy,
    latest_completed_session,
    render_capability_image,
)

ET = ZoneInfo("America/New_York")


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
        # Member publishing intentionally remains unreachable until the exact
        # Owner launch approval changes both mode and scheduler configuration.
        if not self.scheduler_enabled or self.policy.mode != "MEMBER":
            return

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()
