from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cards import build_public_analysis_embed, build_public_trade_embed
from app.bot.general_cards import risk_disclosure_embed, subscription_embed, welcome_embed
from app.domain.public_cards import PublicAnalysisCard, PublicTradeCard
from app.services.membership_access import PriceSnapshot


class PreviewComponentView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=600)
        button = discord.ui.Button(
            label="TEST COMPONENT",
            style=discord.ButtonStyle.secondary,
            custom_id="axis:test:component:v1",
        )
        button.callback = self.respond
        self.add_item(button)

    async def respond(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "测试组件正常；未读取或写入正式订单。",
            ephemeral=True,
        )


def _trade_card(action: str) -> PublicTradeCard:
    payload = {
        "ENTRY": (1, 1, None, None),
        "ADD": (1, 2, Decimal("1.35"), "FIRST"),
        "TP1": (-2, 2, Decimal("2.10"), None),
        "RUNNER": (-1, 1, Decimal("2.45"), None),
        "CLOSE": (-1, 0, Decimal("2.70"), None),
    }[action]
    delta, after, action_price, stage = payload
    return PublicTradeCard(
        public_trade_id="TEST-0001",
        category="SWING",
        action=action,
        action_stage=stage,
        ticker="AXIS",
        expiry=date(2027, 1, 15),
        strike=Decimal("100"),
        option_side="CALL",
        entry_low=Decimal("1.20"),
        entry_high=Decimal("1.30"),
        action_price=action_price,
        avg_cost=Decimal("1.28"),
        sl=Decimal("0.80"),
        tp1=Decimal("2.10"),
        tp2=Decimal("2.70"),
        position_delta_eighths=delta,
        position_after_eighths=after,
        pnl_pct=Decimal("42.5") if action != "ENTRY" else None,
    )


def _analysis_card() -> PublicAnalysisCard:
    return PublicAnalysisCard(
        analysis_code="TEST-A-0001",
        analysis_type="TICKER",
        symbols=("AXIS",),
        sector=None,
        stance="WATCH",
        time_horizon="SWING",
        title="我关注价格在关键结构附近的反应。",
        summary="这是不写入数据库的 Analysis Card 预览。",
        core_thesis="我认为确认信号比提前猜测方向更重要。",
        why_now=("我关注成交与结构是否同步改善。",),
        supporting_points=("测试内容，不构成正式观点。",),
        engine_observations=(),
        key_levels=(),
        projection_path=(),
        invalidation="测试失效条件。",
        catalysts=(),
        risks=("仅用于 Embed 样式测试。",),
        market_conditions=(),
        related_symbols=(),
        observed_at=datetime.now(UTC),
    )


class CardTestingCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        owner_user_id: int | None,
        channel_id: int,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.channel_id = channel_id

    async def _authorize(self, interaction: discord.Interaction) -> bool:
        allowed = (
            interaction.guild is not None
            and interaction.guild.id == self.guild_id
            and interaction.channel_id == self.channel_id
            and interaction.user.id in {interaction.guild.owner_id, self.owner_user_id}
        )
        if not allowed:
            await interaction.response.send_message(
                "该测试命令仅限 Owner 在 card-testing 使用。",
                ephemeral=True,
            )
        return allowed

    async def _send_trade(self, interaction: discord.Interaction, action: str) -> None:
        if not await self._authorize(interaction):
            return
        embed = build_public_trade_embed(_trade_card(action), public_ref=f"TEST-{action}")
        embed.title = f"TEST PREVIEW · {embed.title}"
        await interaction.response.send_message(embed=embed, view=PreviewComponentView())

    @app_commands.command(name="test-signal-card", description="Preview a Signal Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_signal_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "ENTRY")

    @app_commands.command(name="test-analysis-card", description="Preview an Analysis Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_analysis_card(self, interaction: discord.Interaction) -> None:
        if not await self._authorize(interaction):
            return
        embed = build_public_analysis_embed(_analysis_card(), public_ref="TEST-ANALYSIS")
        embed.title = f"TEST PREVIEW · {embed.title}"
        await interaction.response.send_message(embed=embed, view=PreviewComponentView())

    @app_commands.command(name="test-entry-card", description="Preview an Entry Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_entry_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "ENTRY")

    @app_commands.command(name="test-add-card", description="Preview an Add Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_add_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "ADD")

    @app_commands.command(name="test-tp-card", description="Preview a TP Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_tp_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "TP1")

    @app_commands.command(name="test-runner-card", description="Preview a Runner Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_runner_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "RUNNER")

    @app_commands.command(name="test-close-card", description="Preview a Close Card safely")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_close_card(self, interaction: discord.Interaction) -> None:
        await self._send_trade(interaction, "CLOSE")

    @app_commands.command(name="test-general-card", description="Preview AXIS General cards")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_general_card(self, interaction: discord.Interaction) -> None:
        if not await self._authorize(interaction):
            return
        await interaction.response.send_message(
            embeds=[
                welcome_embed(
                    self.guild_id,
                    {
                        "subscriptions": 100000000000000001,
                        "official_results": 100000000000000002,
                        "lobby": 100000000000000003,
                        "member_wins": 100000000000000004,
                        "short_term_alerts": 100000000000000005,
                        "swing_alerts": 100000000000000006,
                        "leaps_alerts": 100000000000000007,
                        "member_chat": 100000000000000008,
                    },
                ),
                subscription_embed(_preview_offers()),
            ],
            view=PreviewComponentView(),
        )

    @app_commands.command(name="test-payment-ui", description="Preview risk and payment UI")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_payment_ui(self, interaction: discord.Interaction) -> None:
        if not await self._authorize(interaction):
            return
        await interaction.response.send_message(
            embed=risk_disclosure_embed(),
            view=PreviewComponentView(),
        )


def _preview_offers() -> dict[str, PriceSnapshot]:
    return {
        "DAY_PASS": PriceSnapshot(
            id=uuid.UUID("00000000-0000-4000-8000-000000000101"),
            plan_type="DAY_PASS",
            pricing_version="DAY_PASS_V1",
            stripe_product_id=None,
            stripe_price_id=None,
            unit_amount=999,
            currency="usd",
            billing_interval=None,
        ),
        "MONTHLY": PriceSnapshot(
            id=uuid.UUID("00000000-0000-4000-8000-000000000102"),
            plan_type="MONTHLY",
            pricing_version="MONTHLY_V1",
            stripe_product_id=None,
            stripe_price_id=None,
            unit_amount=9999,
            currency="usd",
            billing_interval="month",
        ),
    }
