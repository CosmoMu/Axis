from datetime import UTC, date, datetime
from pathlib import Path

from app.bot.spy_0dte_cards import build_spy_capability_embed
from app.services.spy_0dte_desk import (
    ET,
    MoomooSpy0dteProvider,
    Spy0dtePolicy,
    SpyCapabilityReport,
    SpyScoreInputs,
    calculate_score,
    latest_completed_session,
    publishing_slot,
    render_capability_image,
    structure_label,
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
    assert sum(value.weights.values()) == 1


def test_score_is_deterministic_bounded_smoothed_and_labeled() -> None:
    inputs = SpyScoreInputs(100, 80, 60, 40, 20, 0, -20)
    first = calculate_score(inputs, policy())
    second = calculate_score(inputs, policy())
    assert first == second
    assert -100 <= first.raw_score <= 100
    assert (
        calculate_score(inputs, policy(), previous_display_score=-100).display_score
        < first.raw_score
    )
    assert structure_label(70) == "极强偏多"
    assert structure_label(-70) == "极强偏空"
    assert structure_label(0) == "中性"


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
    levels = MoomooSpy0dteProvider._key_levels(
        (724.0,), bars, 764.29, 765.1, 764.8, below=True
    )
    assert levels == (764.0,)
