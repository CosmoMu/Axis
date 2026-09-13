"""Owner-only TEST surface and disabled-by-default scheduler for SPXW 0DTE."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.spxw_0dte_cards import build_spxw_capability_embed
from app.services.spxw_0dte_desk import (
    MoomooSpxw0dteProvider,
    Spxw0dtePolicy,
    next_weekday,
    render_capability_image,
)

ET = ZoneInfo("America/New_York")


class Spxw0dteCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        provider: MoomooSpxw0dteProvider,
        policy: Spxw0dtePolicy,
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

    @app_commands.command(name="test-spxw-0dte", description="测试 AXIS SPXW 0DTE 数据门禁与卡片")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_spxw_0dte(self, interaction: discord.Interaction) -> None:
        if not self._authorized(interaction):
            await interaction.response.send_message(
                "该命令仅限 Owner 在 🧪・卡片测试频道使用。", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        today = datetime.now(ET).date()
        report = await self.provider.probe(next_weekday(today))
        image = render_capability_image(report, self.policy)
        await interaction.edit_original_response(
            embed=build_spxw_capability_embed(report),
            attachments=[discord.File(BytesIO(image), filename="axis-spxw-0dte-test.png")],
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
