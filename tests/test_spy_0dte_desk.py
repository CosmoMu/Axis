from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.bot.spy_0dte_cards import build_spy_capability_embed
from app.market_intelligence.gex_explorer.engine import build_gex_snapshot
from app.market_intelligence.gex_explorer.models import (
    GexByStrike,
    GexIntradayBar,
    GexOptionContract,
    OptionSide,
)
from app.services.spy_0dte_algorithm import (
    SpyDataQuality,
    build_scenarios,
    calculate_bias,
    gamma_regime,
)
from app.services.spy_0dte_desk import (
    ET,
    MoomooSpy0dteProvider,
    Spy0dtePolicy,
    Spy0dteSnapshot,
    SpyCapabilityReport,
    latest_completed_session,
    publishing_slot,
    render_capability_image,
    render_snapshot_image,
)
from app.services.trading_calendar import TradingCalendarService


def policy() -> Spy0dtePolicy:
    return Spy0dtePolicy.load(Path("config/spy_0dte_desk.yaml"))


def report(*, ready: bool = False) -> SpyCapabilityReport:
    return SpyCapabilityReport(
        checked_at=datetime(2026, 9, 13, 22, 0, tzinfo=UTC),
        chain_session=date(2026, 9, 14),
        opend_connected=True,
        spy_chain=True,
        spy_only=True,
        contract_count=390,
        gamma=True,
        implied_volatility=True,
        open_interest=True,
        volume=True,
        bid_ask=True,
        timestamps=True,
        spy_spot=ready,
        spy_5m=ready,
        spot=764.29 if ready else None,
        bar_count=78 if ready else 0,
        error_code=None if ready else "SPY_0DTE_PROVIDER_UNSUPPORTED",
    )


def test_policy_is_member_mode_and_scheduler_contract_is_five_minutes() -> None:
    value = policy()
    assert value.enabled is True
    assert value.mode == "MEMBER"
    assert value.refresh_minutes == 5
    assert sum(value.timeframe_weights.values()) == 1
    assert value.momentum_weight + value.location_weight == 1
    assert value.version == "SPY_0DTE_V3_COSMOS_METHOD"


def test_cosmos_method_bias_and_scenarios_are_deterministic_and_scaled_for_spy() -> None:
    value = policy()
    arguments = dict(
        scores={"1m": 40, "5m": 50, "15m": 30, "1h": 20},
        spot=100.25,
        zero_gamma=100.0,
        call_wall=102.0,
        put_wall=98.0,
        quality=SpyDataQuality.GOOD,
        timeframe_weights=value.timeframe_weights,
        momentum_weight=value.momentum_weight,
        location_weight=value.location_weight,
    )
    first = calculate_bias(**arguments)
    assert first == calculate_bias(**arguments)
    assert -100 <= first[0] <= 100
    points = tuple(GexByStrike(strike, 1, -0.5, 0.5) for strike in range(95, 106))
    scenarios = build_scenarios(first[0], "正 Gamma 控场", 100.25, 102, 98, points)
    assert sum(item.weight for item in scenarios) == 100
    assert scenarios[0].targets == (103, 104)
    assert scenarios[2].targets == (97, 96)
    assert gamma_regime(20, 100, 100.25, 100)[0] == "Zero Gamma 决胜区"


def test_failure_card_is_truthful_and_contains_no_trade_setup_language() -> None:
    embed = build_spy_capability_embed(report())
    text = "\n".join(
        [embed.title or "", embed.description or "", *(field.value for field in embed.fields)]
    ).upper()
    assert "失败关闭" in text
    assert "SPY" in text
    assert "SPX" not in text
    for forbidden in ("CALL SETUP", "PUT SETUP", "ENTRY", "TARGET", "STOP LOSS"):
        assert forbidden not in text
    assert "不构成投资建议" in (embed.footer.text or "")


def test_diagnostic_image_is_png_and_large_enough_for_discord() -> None:
    image = render_capability_image(report(), policy())
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 10_000


def test_formal_cosmos_style_card_is_discord_ready_1400_by_1500_png() -> None:
    timestamp = datetime(2026, 9, 14, 10, 5, tzinfo=ET)
    contracts = tuple(
        GexOptionContract(
            symbol=f"US.SPY260914{side.value[0]}{strike * 1000}",
            expiration=timestamp.date(),
            strike=float(strike),
            side=side,
            open_interest=(strike - 90) * (2 if side is OptionSide.CALL else 1),
            gamma=0.02,
            implied_volatility=0.25,
            volume=100,
        )
        for strike in range(95, 106)
        for side in (OptionSide.CALL, OptionSide.PUT)
    )
    gex = build_gex_snapshot("SPY", 100.25, contracts, timestamp)
    bars = tuple(
        GexIntradayBar(
            timestamp.replace(minute=minute),
            100 + minute / 100,
            100.5 + minute / 100,
            99.5 + minute / 100,
            100.25 + minute / 100,
            1000 + minute,
        )
        for minute in (0, 5, 10, 15)
    )
    scenarios = build_scenarios(24, "正 Gamma 控场", 100.25, 102, 98, gex.by_strike)
    snapshot = Spy0dteSnapshot(
        session_date=timestamp.date(),
        generated_at=timestamp.astimezone(UTC),
        spot=100.25,
        spot_timestamp=timestamp,
        raw_score=24,
        display_score=24,
        structure_label="轻度偏多",
        bias_delta=4,
        day_change=0.75,
        day_change_pct=0.75,
        gamma_regime="正 Gamma 控场",
        gamma_note="更容易来回震荡与均值回归，不追瞬间突破",
        net_gex=gex.net_gex,
        gamma_flip=gex.zero_gamma,
        gamma_magnet=gex.gamma_magnet,
        call_wall=gex.call_wall,
        put_wall=gex.put_wall,
        supports=(99, 98),
        resistances=(101, 102),
        vwap=100.1,
        ema9_5m=100.2,
        volume_ratio=1.2,
        momentum="偏强",
        volume_gamma_bias="中性",
        oi_gamma_bias="偏多",
        expected_move=1.5,
        option_contract_count=len(contracts),
        total_abs_gex=gex.total_abs_gex,
        score_1m=30,
        score_5m=24,
        score_15m=12,
        score_1h=4,
        scenarios=scenarios,
        changes=(),
        data_quality=SpyDataQuality.GOOD,
        source_timestamp=timestamp,
        provider="moomoo",
        stale=False,
        warnings=(),
        policy_version=policy().version,
        gex=gex,
        bars=bars,
    )
    image = render_snapshot_image(snapshot, policy())
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(image)) as rendered:
        assert rendered.size == (1400, 1500)


def test_weekend_probe_uses_latest_completed_session() -> None:
    assert latest_completed_session(datetime(2026, 9, 13, 12, tzinfo=UTC)) == date(2026, 9, 11)
    assert latest_completed_session(datetime(2026, 9, 14, 21, tzinfo=UTC)) == date(2026, 9, 14)


def test_scheduler_uses_five_minute_session_slots_without_weekend_or_close() -> None:
    calendar = TradingCalendarService()
    assert publishing_slot(datetime(2026, 9, 14, 9, 35, tzinfo=ET), policy(), calendar) == (
        date(2026, 9, 14),
        9,
        35,
    )
    assert publishing_slot(datetime(2026, 9, 14, 9, 36, tzinfo=ET), policy(), calendar) is None
    assert publishing_slot(datetime(2026, 9, 14, 16, 0, tzinfo=ET), policy(), calendar) is None
    assert publishing_slot(datetime(2026, 9, 13, 10, 0, tzinfo=ET), policy(), calendar) is None


def test_key_levels_prefer_nearby_price_structure_over_far_gex_level() -> None:
    from app.market_intelligence.gex_explorer.models import GexIntradayBar

    bars = (
        GexIntradayBar(datetime(2026, 9, 11, 15, 55, tzinfo=ET), 765, 765.2, 764.4, 764.7, 1),
        GexIntradayBar(datetime(2026, 9, 11, 16, 0, tzinfo=ET), 764.7, 764.8, 764.0, 764.29, 1),
    )
    levels = MoomooSpy0dteProvider._key_levels((724.0,), bars, 764.29, 765.1, 764.8, below=True)
    assert levels == (764.0,)
