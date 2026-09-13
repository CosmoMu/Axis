from datetime import UTC, date, datetime
from pathlib import Path

from app.bot.spxw_0dte_cards import build_spxw_capability_embed
from app.services.spxw_0dte_desk import (
    Spxw0dtePolicy,
    SpxwCapabilityReport,
    SpxwScoreInputs,
    calculate_score,
    next_weekday,
    render_capability_image,
    structure_label,
)


def policy() -> Spxw0dtePolicy:
    return Spxw0dtePolicy.load(Path("config/spxw_0dte_desk.yaml"))


def report(*, ready: bool = False) -> SpxwCapabilityReport:
    return SpxwCapabilityReport(
        checked_at=datetime(2026, 9, 13, 22, 0, tzinfo=UTC),
        chain_session=date(2026, 9, 14),
        opend_connected=True,
        spxw_chain=True,
        spxw_only=True,
        contract_count=488,
        gamma=True,
        implied_volatility=True,
        open_interest=True,
        volume=True,
        bid_ask=True,
        timestamps=True,
        spx_spot=ready,
        spx_5m=ready,
        error_code=None if ready else "SPXW_0DTE_PROVIDER_UNSUPPORTED",
    )


def test_policy_is_test_only_and_scheduler_contract_is_five_minutes() -> None:
    value = policy()
    assert value.enabled is True
    assert value.mode == "TEST"
    assert value.refresh_minutes == 5
    assert sum(value.weights.values()) == 1


def test_score_is_deterministic_bounded_smoothed_and_labeled() -> None:
    inputs = SpxwScoreInputs(100, 80, 60, 40, 20, 0, -20)
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
    embed = build_spxw_capability_embed(report())
    text = "\n".join(
        [embed.title or "", embed.description or "", *(field.value for field in embed.fields)]
    ).upper()
    assert "SPXW" in text
    assert "失败关闭" in text
    assert "SPY" in text
    for forbidden in ("CALL SETUP", "PUT SETUP", "ENTRY", "TARGET", "STOP LOSS"):
        assert forbidden not in text
    assert "不构成投资建议" in (embed.footer.text or "")


def test_diagnostic_image_is_png_and_large_enough_for_discord() -> None:
    image = render_capability_image(report(), policy())
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 10_000


def test_weekend_chain_probe_uses_next_weekday() -> None:
    assert next_weekday(date(2026, 9, 13)) == date(2026, 9, 14)
    assert next_weekday(date(2026, 9, 14)) == date(2026, 9, 14)
