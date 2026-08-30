from __future__ import annotations

import math
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.bot.cards import build_public_trade_embed
from app.bot.cogs.card_review import CardReviewCog
from app.domain.public_cards import PublicTradeCard
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.models import DailyBar, StockMarketBundle
from app.market_intelligence.trade_plan import (
    SwingLeapsTradePlanService,
    TradePlanArtifact,
    render_swing_leaps_entry_chart,
    resolve_entry_plan,
    visible_entry_plan_labels,
)
from app.services.trade_publication import PublicationClaim, PublicationResult


def _bars() -> tuple[DailyBar, ...]:
    start = datetime(2026, 5, 1, 16, tzinfo=UTC)
    output = []
    for index in range(90):
        close = 96 + index * 0.17 + math.sin(index / 4) * 1.6
        open_price = close - math.sin(index / 3) * 0.5
        output.append(
            DailyBar(
                timestamp=start + timedelta(days=index),
                open=open_price,
                high=max(open_price, close) + 1.1,
                low=min(open_price, close) - 1.0,
                close=close,
                volume=1_000_000 + index * 10_000,
            )
        )
    return tuple(output)


def _card(category: str = "SWING", *, complete_plan: bool = True) -> PublicTradeCard:
    return PublicTradeCard(
        public_trade_id="SW-0041" if category == "SWING" else "LP-0041",
        category=category,
        action="ENTRY",
        action_stage=None,
        ticker="IGV",
        expiry=date(2027, 9, 18),
        strike=Decimal("115"),
        option_side="CALL",
        entry_low=Decimal("1.20"),
        entry_high=Decimal("1.28"),
        action_price=None,
        avg_cost=None,
        sl=None,
        tp1=None,
        tp2=None,
        position_delta_eighths=1,
        position_after_eighths=1,
        pnl_pct=None,
        current_stock=Decimal("109.27") if complete_plan else None,
        starter=Decimal("109.05") if complete_plan else None,
        add_zone_low=Decimal("108.23") if complete_plan else None,
        add_zone_high=Decimal("108.85") if complete_plan else None,
        stock_sl=Decimal("104.14") if complete_plan else None,
        stock_pt1=Decimal("111.39"),
        stock_pt2=Decimal("113.46") if complete_plan else None,
        stock_pt3=Decimal("115.53") if complete_plan else None,
        fib_0618=Decimal("107.92") if complete_plan else None,
        public_thesis="关键结构维持时，观察 Starter 入场后的目标推进。",
    )


@pytest.mark.parametrize("category", ["SWING", "LEAPS"])
def test_entry_public_card_uses_new_chinese_plan_format(category: str) -> None:
    embed = build_public_trade_embed(_card(category), public_ref="P-0041")
    payload = embed.to_dict()
    rendered = str(payload)

    assert payload["title"].endswith("STARTER ENTRY")
    assert "当前股价" in rendered
    assert "止盈目标" in rendered
    assert "Add Zone" in rendered
    assert "Fib 0.618" in rendered
    assert "ENTRY TRIGGERED · 1/8 仓位" in rendered
    assert payload["footer"]["text"] == "AXIS · P-0041"
    assert "P-F0ECED1A6B6E" not in rendered
    assert "本次操作价格" not in rendered
    assert "AXIS Internal" not in rendered


def test_entry_card_hides_missing_optional_plan_fields_and_internal_long_ref() -> None:
    card = _card(complete_plan=False)
    embed = build_public_trade_embed(card, public_ref="P-F0ECED1A6B6E")
    rendered = str(embed.to_dict())

    assert "PT1" in rendered
    assert "PT3" not in rendered
    assert "Add Zone" not in rendered
    assert "Fib 0.618" not in rendered
    assert "P-F0ECED1A6B6E" not in rendered
    assert embed.footer.text == "AXIS · SWING"


def test_mentor_points_win_and_axis_fills_only_missing_fields() -> None:
    bars = _bars()
    analysis = analyze_stock("IGV", bars, sector_etf="SPY")
    mentor = _card()
    resolved, provenance = resolve_entry_plan(mentor, analysis, bars)

    assert resolved.current_stock == Decimal("109.27")
    assert resolved.stock_pt1 == Decimal("111.39")
    assert resolved.stock_pt2 == Decimal("113.46")
    assert resolved.stock_pt3 == Decimal("115.53")
    assert resolved.fib_0618 == Decimal("107.92")
    assert provenance["stock_pt1"] == "MENTOR_INPUT"
    assert provenance["fib_0618"] == "MENTOR_INPUT"

    partial = _card(complete_plan=False)
    filled, fill_provenance = resolve_entry_plan(partial, analysis, bars)
    assert filled.stock_pt1 == Decimal("111.39")
    assert fill_provenance["stock_pt1"] == "MENTOR_INPUT"
    assert filled.current_stock is not None
    assert filled.starter is not None
    assert filled.fib_0618 is not None
    assert fill_provenance["current_stock"] == "STOCK_ANALYST"
    assert fill_provenance["fib_0618"] == "STOCK_ANALYST"


def test_axis_never_backfills_a_later_pt_below_explicit_mentor_pt1() -> None:
    bars = _bars()
    base = analyze_stock("IGV", bars, sector_etf="SPY")
    analysis = replace(
        base,
        current_price=6.10,
        resistance_levels=(),
        support_levels=(),
        scenarios=(
            replace(
                base.scenarios[0],
                targets=(6.3556, 6.4838),
            ),
        ),
    )
    card = replace(
        _card(complete_plan=False),
        current_stock=Decimal("6.10"),
        stock_pt1=Decimal("7.40"),
        stock_pt2=None,
        stock_pt3=None,
    )

    resolved, provenance = resolve_entry_plan(card, analysis, bars)

    assert resolved.stock_pt1 == Decimal("7.40")
    assert resolved.stock_pt2 is None
    assert resolved.stock_pt3 is None
    assert "stock_pt2" not in provenance
    assert "stock_pt3" not in provenance


def test_deterministic_chart_contains_all_supported_plan_labels() -> None:
    card = _card()
    first = render_swing_leaps_entry_chart(card, _bars())
    second = render_swing_leaps_entry_chart(card, _bars())

    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert visible_entry_plan_labels(card) == (
        "CURRENT",
        "STARTER",
        "ADD ZONE",
        "SL",
        "PT1",
        "PT2",
        "PT3",
        "0.618",
    )


class _Provider:
    async def fetch(self, ticker: str) -> StockMarketBundle:
        assert ticker == "IGV"
        return StockMarketBundle("IGV", _bars(), "SPY", None, None)


@pytest.mark.asyncio
async def test_plan_service_generates_real_candle_png() -> None:
    artifact = await SwingLeapsTradePlanService(_Provider()).prepare(_card())
    assert artifact.chart_png is not None
    assert artifact.chart_png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_swing_entry_publication_sends_chart_attachment() -> None:
    card = _card()
    claim = PublicationClaim(
        publication_id=uuid.uuid4(),
        draft_id=uuid.uuid4(),
        claim_token="claim-token",
        should_publish=True,
        already_published=False,
        channel_id=123,
        public_ref="P-0041",
        card=card,
        message_id=None,
    )

    class Publication:
        async def claim(self, *args: object, **kwargs: object) -> PublicationClaim:
            return claim

        async def finalize(self, *args: object, **kwargs: object) -> PublicationResult:
            return PublicationResult(
                publication_id=claim.publication_id,
                draft_id=claim.draft_id,
                trade_id=uuid.uuid4(),
                trade_event_id=uuid.uuid4(),
                message_id=999,
                public_trade_id="SW-0041",
            )

    class Channel:
        def __init__(self) -> None:
            self.sent: dict[str, object] | None = None

        async def history(self, *, limit: int):
            assert limit == 200
            if False:
                yield None

        async def send(self, **kwargs: object) -> SimpleNamespace:
            self.sent = kwargs
            return SimpleNamespace(id=999)

    channel = Channel()

    class Bot:
        user = SimpleNamespace(id=7)

        def get_channel(self, channel_id: int) -> Channel:
            assert channel_id == 123
            return channel

    class Plan:
        async def prepare(self, original: PublicTradeCard) -> TradePlanArtifact:
            assert original == card
            return TradePlanArtifact(card, b"\x89PNG\r\n\x1a\nchart", {})

    controller = CardReviewCog.__new__(CardReviewCog)
    controller.bot = Bot()  # type: ignore[assignment]
    controller.publication_service = Publication()  # type: ignore[assignment]
    controller.service = SimpleNamespace(get=lambda _: None)  # type: ignore[assignment]
    controller.tracking_service = SimpleNamespace()  # type: ignore[assignment]
    controller.trade_plan_service = Plan()  # type: ignore[assignment]

    async def get_draft(_: uuid.UUID) -> SimpleNamespace:
        return draft

    draft = SimpleNamespace(
        id=claim.draft_id,
        selected_category="SWING",
        category_suggestion="SWING",
    )
    controller.service = SimpleNamespace(get=get_draft)  # type: ignore[assignment]
    await controller.publish_draft(draft)  # type: ignore[arg-type]

    assert channel.sent is not None
    assert channel.sent["file"].filename == "axis-sw-0041-entry-plan.png"  # type: ignore[union-attr]
    assert channel.sent["embed"].image.url == (  # type: ignore[union-attr]
        "attachment://axis-sw-0041-entry-plan.png"
    )
