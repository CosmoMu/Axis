from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.bot.cards import build_analysis_review_embed
from app.market_intelligence.gex_explorer import (
    AXIS_GEX_EXPLORER,
    GexOptionContract,
    OptionSide,
    build_gex_snapshot,
)
from app.market_intelligence.stock_analyst import (
    AXIS_STOCK_ANALYST,
    AxisStockAnalystService,
    sanitize_input_analysis,
)
from app.market_intelligence.stock_analyst.chart import (
    render_stock_analysis_chart,
    resolve_projection_path,
    stock_chart_title,
)
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.models import (
    DailyBar,
    StockMarketBundle,
)
from app.services.analysis_pipeline import AnalysisDraftSnapshot


def bars(*, drift: float = 0.0015, phase: float = 0.0) -> tuple[DailyBar, ...]:
    timestamp = datetime(2025, 1, 2, 16, tzinfo=UTC)
    price = 100.0
    output = []
    while len(output) < 240:
        if timestamp.weekday() < 5:
            index = len(output)
            change = drift + math.sin(index * 0.31 + phase) * 0.004
            opening = price * (1 + change * 0.25)
            close = price * (1 + change)
            output.append(
                DailyBar(
                    timestamp=timestamp,
                    open=opening,
                    high=max(opening, close) * 1.008,
                    low=min(opening, close) * 0.992,
                    close=close,
                    volume=2_000_000 * (1 + 0.2 * math.sin(index * 0.17)),
                )
            )
            price = close
        timestamp += timedelta(days=1)
    return tuple(output)


class FakeDailyProvider:
    async def fetch(self, ticker: str) -> StockMarketBundle:
        return StockMarketBundle(
            ticker=ticker.upper(),
            bars=bars(),
            sector_etf="SMH",
            sector_bars=bars(drift=0.0012, phase=0.5),
            benchmark_bars=bars(drift=0.0007, phase=1.0),
        )


def test_axis_stock_analyst_builds_structure_levels_scenarios_and_unified_png() -> None:
    history = bars()
    analysis = analyze_stock(
        "NVDA",
        history,
        sector_etf="SMH",
        sector_bars=bars(drift=0.0012),
        benchmark_bars=bars(drift=0.0007),
    )
    route = (
        {"direction": "DOWN", "price": 127.0, "label": "回踩"},
        {"direction": "UP", "price": None, "label": "反弹"},
    )

    resolved = resolve_projection_path(analysis, route)
    rendered = render_stock_analysis_chart(analysis, history, projection_points=route)

    assert AXIS_STOCK_ANALYST == "AXIS Stock Analyst"
    assert stock_chart_title("nvda") == "NVDA · AXIS STOCK ANALYST"
    assert "TEST" not in stock_chart_title("nvda")
    assert analysis.support_levels and analysis.resistance_levels
    assert len(analysis.volume_profile_nodes) == 24
    assert sum(item.model_weight_percent for item in analysis.scenarios) == pytest.approx(100)
    assert analysis.sector_rotation_phase is not None
    assert resolved is not None and resolved[0][1] == 127.0
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(rendered) > 20_000


def test_axis_stock_analyst_rejects_history_shorter_than_cosmos_minimum() -> None:
    history = bars()[-54:]

    with pytest.raises(ValueError, match="at least 100 daily bars"):
        analyze_stock(
            "SPCX",
            history,
            sector_etf="SPY",
            sector_bars=bars(drift=0.0012),
            benchmark_bars=bars(drift=0.0007),
        )


def test_analysis_viewpoint_is_normalized_to_neutral_axis_voice() -> None:
    payload = {
        "title": "作者预期的路径",
        "summary": "作者的主观预期是先回踩。",
        "core_thesis": "输入认为当前位置值得关注。",
        "invalidation": "原文认为跌破后失效。",
        "why_now": ["作者认为催化临近。"],
        "supporting_points": ["原作者预期成交量改善。"],
        "catalysts": [],
        "risks": [],
        "market_conditions": [],
        "engine_observations": [],
        "key_levels": [],
    }

    normalized = sanitize_input_analysis(payload)

    assert normalized["summary"] == "先回踩。"
    assert normalized["core_thesis"] == "当前位置值得关注。"
    assert normalized["invalidation"] == "跌破后失效。"
    assert normalized["why_now"] == ["催化临近。"]
    assert normalized["supporting_points"] == ["成交量改善。"]


def test_existing_analysis_review_renders_in_neutral_axis_voice() -> None:
    draft = AnalysisDraftSnapshot(
        id=uuid.uuid4(),
        guild_id=1543309921066684567,
        draft_code="A-00001",
        status="PENDING_REVIEW",
        normalized={
            "analysis_type": "TICKER",
            "symbols": ["NVDA"],
            "stance": "BULLISH",
            "time_horizon": "SWING",
            "summary": "作者的主观预期是先回踩。",
            "core_thesis": "原文认为关键位仍有效。",
            "why_now": ["作者认为催化临近。"],
            "supporting_points": [],
            "engine_observations": [],
            "key_levels": [],
        },
        mentor_name="Vincent",
        missing_fields=(),
        warnings=(),
        confidence=None,
        review_channel_id=None,
        review_message_id=None,
        revision=1,
        version=1,
        chart_source=None,
        normalized_mentor={},
        market_context={},
        conflicts=(),
        chart_render_error=None,
    )

    rendered = build_analysis_review_embed(draft).to_dict()
    serialized = str(rendered)

    assert "先回踩" in serialized
    assert "关键位仍有效" in serialized
    assert "我认为" not in serialized
    assert "作者" not in serialized


@pytest.mark.asyncio
async def test_axis_stock_analyst_service_is_provider_injected_and_cosmos_independent() -> None:
    service = AxisStockAnalystService(
        host="127.0.0.1",
        port=11111,
        provider=FakeDailyProvider(),  # type: ignore[arg-type]
    )

    result = await service.query("NVDA", projection_points=None)

    assert result.context["ticker"] == "NVDA"
    assert result.context["sector_etf"] == "SMH"
    assert result.chart_png is not None and result.chart_png.startswith(b"\x89PNG")


def test_axis_gex_explorer_calculates_walls_regime_and_iv_fallback() -> None:
    now = datetime(2026, 8, 28, 11, 0, tzinfo=UTC)
    expiry = date(2026, 9, 18)
    contracts = (
        GexOptionContract("NVDA-C-130", expiry, 130, OptionSide.CALL, 1_500, gamma=0.018),
        GexOptionContract("NVDA-C-140", expiry, 140, OptionSide.CALL, 2_500, gamma=0.014),
        GexOptionContract("NVDA-P-120", expiry, 120, OptionSide.PUT, 2_000, gamma=0.017),
        GexOptionContract(
            "NVDA-P-110",
            expiry,
            110,
            OptionSide.PUT,
            900,
            gamma=None,
            implied_volatility=0.42,
        ),
    )

    snapshot = build_gex_snapshot("NVDA", 128.0, contracts, now)

    assert AXIS_GEX_EXPLORER == "AXIS GEX Explorer"
    assert snapshot.included_contracts == 4
    assert snapshot.call_wall == 140
    assert snapshot.put_wall in {110, 120}
    assert snapshot.zero_gamma is not None
    assert snapshot.total_abs_gex > 0
    assert -1 <= snapshot.normalized_net_gex <= 1
    assert "Black-Scholes" in snapshot.gamma_method
    assert "并非真实持仓" in snapshot.dealer_sign_assumption
