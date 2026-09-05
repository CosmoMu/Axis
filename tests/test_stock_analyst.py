from __future__ import annotations

import asyncio
import math
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.bot.cogs.stock_analyst import stock_authorization_error
from app.bot.stock_analyst_cards import build_stock_analyst_embed
from app.market_intelligence.stock_analyst.engine import STRATEGY_VERSION, analyze_stock
from app.market_intelligence.stock_analyst.market_data import (
    MassiveDailyBarProvider,
    StockMarketDataError,
)
from app.market_intelligence.stock_analyst.models import DailyBar
from app.market_intelligence.stock_analyst.service import (
    AxisStockAnalystError,
    AxisStockAnalystResult,
)
from app.services.stock_analyst import (
    StockAnalystError,
    StockAnalystPolicy,
    StockAnalystQueryService,
    normalize_stock_ticker,
)


def _bars(drift: float = 0.0015, phase: float = 0.0) -> tuple[DailyBar, ...]:
    start = datetime(2025, 1, 2, 16, tzinfo=UTC)
    price = 100.0
    output = []
    for index in range(240):
        change = drift + math.sin(index * 0.31 + phase) * 0.004
        opening = price * (1 + change * 0.25)
        close = price * (1 + change)
        output.append(
            DailyBar(
                timestamp=start + timedelta(days=index),
                open=opening,
                high=max(opening, close) * 1.008,
                low=min(opening, close) * 0.992,
                close=close,
                volume=2_000_000 * (1 + 0.2 * math.sin(index * 0.17)),
            )
        )
        price = close
    return tuple(output)


class _Session:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def commit(self) -> None:
        return None


class _Database:
    def __init__(self) -> None:
        self.rows: list[object] = []

    @asynccontextmanager
    async def session(self):
        yield _Session(self.rows)


class _Analyst:
    def __init__(self, *, delay: float = 0.0, market_status: str = "closed") -> None:
        self.provider = SimpleNamespace(name="massive")
        self.calls: list[str] = []
        self.delay = delay
        self.market_status = market_status

    async def query(self, ticker: str, *, include_chart: bool = True):
        self.calls.append(ticker)
        if self.delay:
            await asyncio.sleep(self.delay)
        history = _bars()
        analysis = analyze_stock(ticker, history, sector_etf="SPY")
        source = datetime.now(UTC) - timedelta(hours=1)
        return AxisStockAnalystResult(
            context={
                "provider": "massive",
                "market_timestamp": source.isoformat(),
                "market_status": self.market_status,
            },
            chart_png=b"\x89PNG\r\n\x1a\nchart",
            analysis=analysis,
            daily_bars=history,
        )


class _FailingAnalyst:
    provider = SimpleNamespace(name="massive")

    async def query(self, ticker: str, *, include_chart: bool = True):
        raise AxisStockAnalystError("STOCK_ANALYST_PROVIDER_FAILURE")


class _EmptyMassiveResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, *, content_type=None):
        return {"status": "OK", "queryCount": 0}


class _EmptyMassiveSession:
    def get(self, url, *, params=None):
        return _EmptyMassiveResponse()


def _policy() -> StockAnalystPolicy:
    return StockAnalystPolicy(
        version=STRATEGY_VERSION,
        provider="massive",
        daily_lookback_calendar_days=550,
        minimum_daily_sessions=120,
        maximum_data_age_seconds=900,
        timeout_seconds=15,
        provider_concurrency=4,
        timeframe="1D",
        chart_sessions=82,
        cache_seconds=60,
        user_cooldown_seconds=5,
        guild_fresh_requests_per_minute=20,
        maximum_latency_seconds=20,
    )


@pytest.mark.parametrize(
    ("ticker", "drift", "phase", "trend", "poc", "val", "vah", "first_support"),
    [
        ("NVDA", 0.0015, 0.0, 74.7, 136.155974, 130.6313, 142.530597, 144.005607),
        ("TSLA", -0.0005, 0.7, 9.0, 91.156146, 89.860239, 93.028013, 87.844383),
        ("SPY", 0.0, 0.3, 49.0, 100.79102, 99.994273, 102.47304, 99.111755),
    ],
)
def test_cosmos_v0_1_parity_fixture(
    ticker: str,
    drift: float,
    phase: float,
    trend: float,
    poc: float,
    val: float,
    vah: float,
    first_support: float,
) -> None:
    analysis = analyze_stock(ticker, _bars(drift, phase), sector_etf="SPY")

    assert analysis.trend_score == trend
    assert analysis.point_of_control == pytest.approx(poc)
    assert analysis.value_area_low == pytest.approx(val)
    assert analysis.value_area_high == pytest.approx(vah)
    assert analysis.support_levels[0].price == pytest.approx(first_support)
    assert sum(item.model_weight_percent for item in analysis.scenarios) == pytest.approx(100)


def test_ticker_normalization_and_phase1_permissions() -> None:
    assert normalize_stock_ticker("nvda") == "NVDA"
    assert normalize_stock_ticker("$spy") == "SPY"
    with pytest.raises(StockAnalystError):
        normalize_stock_ticker("bad ticker")
    base = {
        "expected_guild_id": 1,
        "owner_user_id": 2,
        "card_testing_channel_id": 3,
        "mode": "TEST",
    }
    assert stock_authorization_error(guild_id=1, channel_id=3, user_id=2, **base) is None
    assert (
        stock_authorization_error(guild_id=1, channel_id=4, user_id=2, **base)
        == "TEST_CHANNEL_REQUIRED"
    )
    for unauthorized_user in (4, 5, 6, 7):
        assert (
            stock_authorization_error(
                guild_id=1,
                channel_id=3,
                user_id=unauthorized_user,
                **base,
            )
            == "PERMISSION_DENIED"
        )


@pytest.mark.asyncio
async def test_cache_separation_expiry_version_and_read_only_audit() -> None:
    database, analyst = _Database(), _Analyst()
    service = StockAnalystQueryService(database, analyst, _policy())  # type: ignore[arg-type]
    first = await service.query(
        guild_id=1, actor_user_id=2, ticker="SPY", enforce_rate_limits=False
    )
    second = await service.query(
        guild_id=1, actor_user_id=2, ticker="SPY", enforce_rate_limits=False
    )
    assert not first.cache_hit and second.cache_hit and analyst.calls == ["SPY"]
    await service.query(guild_id=1, actor_user_id=2, ticker="QQQ", enforce_rate_limits=False)
    assert analyst.calls == ["SPY", "QQQ"]
    spy_key = next(key for key in service._cache if key[0] == "SPY")
    service._cache[spy_key] = replace(service._cache[spy_key], created_monotonic=0.0)
    await service.query(guild_id=1, actor_user_id=2, ticker="SPY", enforce_rate_limits=False)
    assert analyst.calls.count("SPY") == 2
    service.policy = replace(service.policy, version="COSMOS_STOCK_ANALYST_V0_2")
    await service.query(guild_id=1, actor_user_id=2, ticker="SPY", enforce_rate_limits=False)
    assert analyst.calls.count("SPY") == 3
    action_types = {getattr(row, "action_type", None) for row in database.rows}
    assert action_types <= {
        "STOCK_ANALYST_REQUESTED",
        "STOCK_ANALYST_CACHE_HIT",
        "STOCK_ANALYST_CACHE_MISS",
        "STOCK_ANALYST_GENERATED",
    }


@pytest.mark.asyncio
async def test_singleflight_rate_limit_and_stale_cache_label() -> None:
    analyst = _Analyst(delay=0.05, market_status="open")
    service = StockAnalystQueryService(_Database(), analyst, _policy())  # type: ignore[arg-type]
    results = await asyncio.gather(
        *(
            service.query(
                guild_id=1,
                actor_user_id=user,
                ticker="META",
                enforce_rate_limits=False,
            )
            for user in range(10, 14)
        )
    )
    assert analyst.calls == ["META"]
    assert all(result.stale for result in results)
    cached = await service.query(
        guild_id=1,
        actor_user_id=20,
        ticker="META",
        enforce_rate_limits=False,
    )
    assert cached.cache_hit and cached.stale
    limited = StockAnalystQueryService(_Database(), _Analyst(), _policy())  # type: ignore[arg-type]
    await limited.query(guild_id=1, actor_user_id=2, ticker="AAPL")
    with pytest.raises(StockAnalystError, match="STOCK_ANALYST_USER_COOLDOWN"):
        await limited.query(guild_id=1, actor_user_id=2, ticker="AAPL")


@pytest.mark.asyncio
async def test_guild_fresh_request_limit_is_independent_of_user_cooldown() -> None:
    policy = replace(_policy(), guild_fresh_requests_per_minute=1)
    service = StockAnalystQueryService(_Database(), _Analyst(), policy)  # type: ignore[arg-type]
    await service.query(guild_id=1, actor_user_id=2, ticker="SPY")

    with pytest.raises(StockAnalystError, match="STOCK_ANALYST_GUILD_RATE_LIMIT"):
        await service.query(guild_id=1, actor_user_id=3, ticker="QQQ")


@pytest.mark.asyncio
async def test_provider_failure_is_stable_and_audited_without_sensitive_detail() -> None:
    database = _Database()
    service = StockAnalystQueryService(database, _FailingAnalyst(), _policy())  # type: ignore[arg-type]

    with pytest.raises(StockAnalystError, match="STOCK_ANALYST_PROVIDER_FAILURE"):
        await service.query(
            guild_id=1,
            actor_user_id=2,
            ticker="NVDA",
            enforce_rate_limits=False,
        )

    failures = [
        row for row in database.rows if getattr(row, "action_type", None) == "STOCK_ANALYST_FAILED"
    ]
    assert len(failures) == 1
    assert failures[0].after_json["error_type"] == "STOCK_ANALYST_PROVIDER_FAILURE"


@pytest.mark.asyncio
async def test_massive_success_with_zero_results_is_invalid_symbol() -> None:
    session = _EmptyMassiveSession()
    provider = MassiveDailyBarProvider(api_key="test", session=session)  # type: ignore[arg-type]

    with pytest.raises(StockMarketDataError, match="AXIS_STOCK_SYMBOL_NOT_FOUND"):
        await provider._bars(session, "NOTREAL", mandatory=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_card_uses_same_structured_levels_as_chart_result() -> None:
    service = StockAnalystQueryService(_Database(), _Analyst(), _policy())  # type: ignore[arg-type]
    result = await service.query(
        guild_id=1,
        actor_user_id=2,
        ticker="NVDA",
        enforce_rate_limits=False,
    )
    rendered = str(build_stock_analyst_embed(result).to_dict())
    assert "AXIS STOCK ANALYST · TEST" in rendered
    assert f"${result.analysis.support_levels[0].price:,.2f}" in rendered
    assert f"${result.analysis.resistance_levels[0].price:,.2f}" in rendered
    assert result.structured_result["support_levels"][0] == result.analysis.support_levels[0].price
    assert (
        result.structured_result["resistance_levels"][0]
        == result.analysis.resistance_levels[0].price
    )
    assert result.chart_png.startswith(b"\x89PNG")
    assert time.monotonic() > 0
