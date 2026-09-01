from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cards import (
    build_daily_results_snapshot_embed,
    build_public_analysis_embed,
    build_public_trade_embed,
    build_short_term_entry_embed,
    build_short_term_tracking_embed,
)
from app.bot.general_cards import risk_disclosure_embed, subscription_embed, welcome_embed
from app.domain.public_cards import (
    PublicAnalysisCard,
    PublicTradeCard,
    ShortTermEntryCard,
    ShortTermTrackingCard,
)
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


def _results_snapshot(*, review: bool) -> dict[str, object]:
    return {
        "title": "AXIS DAILY RESULTS · DRAFT" if review else "AXIS DAILY RESULTS",
        "trading_date": "2026-08-31",
        "status": "DRAFT",
        "scheduled_publish_at": "2026-08-31T16:15:00-04:00",
        "sections": [
            {
                "label": "SHORT-TERM",
                "lines": [
                    "✓ ST-TEST · NVDA 200C (LOTTO) +136%"
                    if review
                    else "ST-TEST · NVDA 200C (LOTTO) +136%"
                ],
            },
            {
                "label": "SWING",
                "lines": [
                    "✓ SW-TEST · GOOGL 400C\nTP1 +42% · TP2 +60% · 最高收益 +70%"
                    if review
                    else "SW-TEST · GOOGL 400C\nTP1 +42% · TP2 +60% · 最高收益 +70%"
                ],
            },
            {"label": "LEAPS", "lines": []},
        ],
        "footer": (
            "Manager Review" if review else "Past performance does not guarantee future results."
        ),
    }


class PreviewResultsReviewView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=600)
        definitions = (
            ("MANAGE TRADES", discord.ButtonStyle.secondary, self.manage),
            ("EDIT CARD", discord.ButtonStyle.secondary, self.edit),
            ("PREVIEW", discord.ButtonStyle.primary, self.preview),
            ("PUBLISH NOW", discord.ButtonStyle.success, self.publish),
        )
        for label, style, callback in definitions:
            button = discord.ui.Button(label=label, style=style)
            button.callback = callback
            self.add_item(button)

    async def manage(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "TEST：Include / Exclude / Re-Include 由自动化测试覆盖；未写入正式历史。",
            ephemeral=True,
        )

    async def edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "TEST：Display Edit / Correct Result Audit 已通过；未写入正式历史。",
            ephemeral=True,
        )

    async def preview(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_daily_results_snapshot_embed(
                _results_snapshot(review=False),
                review=False,
            ),
            ephemeral=True,
        )

    async def publish(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "TEST Publish Now：不会发送到 results，也不会写入数据库。",
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
        current_stock=Decimal("109.27"),
        starter=Decimal("109.05"),
        add_zone_low=Decimal("108.23"),
        add_zone_high=Decimal("108.85"),
        stock_sl=Decimal("104.14"),
        stock_pt1=Decimal("111.39"),
        stock_pt2=Decimal("113.46"),
        stock_pt3=Decimal("115.53"),
        fib_0618=Decimal("107.92"),
        public_thesis="关键结构维持时，先观察 Starter 入场后的目标推进。",
    )


def _analysis_card() -> PublicAnalysisCard:
    return PublicAnalysisCard(
        analysis_code="TEST-A-0001",
        analysis_type="TICKER",
        symbols=("AXIS",),
        sector=None,
        stance="WATCH",
        title="价格正在关键结构附近观察反应。",
        summary="这是不写入数据库的 Analysis Card 预览。",
        core_thesis="确认信号比提前猜测方向更重要。",
        key_levels=(),
        indicators=(),
        market_profile={},
        top_scenario=None,
        prediction_path=(),
        invalidation="测试失效条件。",
        risks=("仅用于 Embed 样式测试。",),
        market_conditions=(),
        methodology_notice=None,
        market_as_of=None,
        observed_at=datetime.now(UTC),
    )


def _short_term_entry_card() -> ShortTermEntryCard:
    return ShortTermEntryCard(
        public_trade_id="ST-TEST",
        ticker="NVDA",
        expiry=date(2026, 8, 31),
        strike=Decimal("500"),
        option_side="CALL",
        entry_price=Decimal("1.20"),
    )


def _short_term_tracking_card(card_type: str) -> ShortTermTrackingCard:
    return ShortTermTrackingCard(
        public_trade_id="ST-TEST",
        card_type=card_type,
        ticker="NVDA",
        expiry=date(2026, 8, 31),
        strike=Decimal("500"),
        option_side="CALL",
        price=Decimal("1.82"),
        return_pct=Decimal("52"),
        highest_return_pct=Decimal("136") if card_type == "EXPIRED" else None,
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

    async def _send_short_term(self, interaction: discord.Interaction, card_type: str) -> None:
        if not await self._authorize(interaction):
            return
        embed = build_short_term_tracking_embed(
            _short_term_tracking_card(card_type), public_ref=f"TEST-{card_type}"
        )
        embed.title = f"TEST PREVIEW · {embed.title}"
        await interaction.response.send_message(embed=embed, view=PreviewComponentView())

    @app_commands.command(name="test-short-entry", description="Preview a Short-Term Entry Card")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_short_entry(self, interaction: discord.Interaction) -> None:
        if not await self._authorize(interaction):
            return
        embed = build_short_term_entry_embed(
            _short_term_entry_card(), public_ref="TEST-SHORT-ENTRY"
        )
        embed.title = f"TEST PREVIEW · {embed.title}"
        await interaction.response.send_message(embed=embed, view=PreviewComponentView())

    @app_commands.command(name="test-short-tp", description="Preview a Short-Term TP Card")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_short_tp(self, interaction: discord.Interaction) -> None:
        await self._send_short_term(interaction, "TP1")

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

    @app_commands.command(
        name="test-results-review",
        description="Preview Daily Results Review without production writes",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def test_results_review(self, interaction: discord.Interaction) -> None:
        if not await self._authorize(interaction):
            return
        await interaction.response.send_message(
            content="TEST ENVIRONMENT · no production data writes",
            embed=build_daily_results_snapshot_embed(
                _results_snapshot(review=True),
                review=True,
            ),
            view=PreviewResultsReviewView(),
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
