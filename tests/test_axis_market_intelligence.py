from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.market_intelligence.gex_explorer import (
    AXIS_GEX_EXPLORER,
    GexOptionContract,
    OptionSide,
    build_gex_snapshot,
)
from app.market_intelligence.stock_analyst import (
    AXIS_STOCK_ANALYST,
    AxisStockAnalystService,
)
from app.market_intelligence.stock_analyst.chart import (
    render_stock_analysis_chart,
    resolve_projection_path,
)
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.models import (
    DailyBar,
    StockMarketBundle,
)


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
    assert analysis.support_levels and analysis.resistance_levels
    assert len(analysis.volume_profile_nodes) == 24
    assert sum(item.model_weight_percent for item in analysis.scenarios) == pytest.approx(100)
    assert analysis.sector_rotation_phase is not None
    assert resolved is not None and resolved[0][1] == 127.0
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(rendered) > 20_000


def test_axis_stock_analyst_supports_new_listing_with_reduced_conviction() -> None:
    history = bars()[-54:]

    analysis = analyze_stock(
        "SPCX",
        history,
        sector_etf="SPY",
        sector_bars=bars(drift=0.0012),
        benchmark_bars=bars(drift=0.0007),
    )
    rendered = render_stock_analysis_chart(analysis, history)

    assert analysis.history_sessions == 54
    assert analysis.history_mode == "LIMITED"
    assert "limited_history_under_120_sessions" in analysis.unavailable_data
    assert abs(analysis.trend_score - 50) <= 32.5
    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")


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
