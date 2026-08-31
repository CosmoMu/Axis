from decimal import Decimal
from pathlib import Path

from app.services.short_term_policy import ShortTermTrackingPolicy

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"


def test_short_term_policy_has_exact_configured_tp_levels() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)

    assert policy.version == "ST_TRACKING_V4"
    assert policy.price_source == "MID"
    expected_returns = [10, 20, *range(50, 1001, 25)]
    assert [(item.label, item.return_pct) for item in policy.tp_levels] == [
        (f"TP{index}", return_pct)
        for index, return_pct in enumerate(expected_returns, start=1)
    ]
    assert policy.crossed_tp_levels(
        Decimal("130"), {"TP1", "TP2", "TP3", "TP4", "TP5"}
    ) == tuple(
        item for item in policy.tp_levels if item.label == "TP6"
    )


def test_tracking_protection_locks_the_previous_tp_level() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)
    entry = Decimal("1.20")
    cases = (
        (set(), "0.60", -50),
        ({"TP1"}, "1.20", 0),
        ({"TP1", "TP2"}, "1.20", 0),
        ({"TP1", "TP2", "TP3"}, "1.44", 20),
        ({"TP1", "TP2", "TP3", "TP4"}, "1.80", 50),
        ({"TP1", "TP2", "TP3", "TP4", "TP5"}, "2.10", 75),
    )
    for hit, expected_price, expected_return in cases:
        price, return_pct, _reason = policy.protection_for(entry, hit)
        assert price == Decimal(expected_price)
        assert return_pct == expected_return


def test_fast_momentum_and_slow_pullback_policy() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)

    fast_60 = policy.momentum_drawdown(
        high_price=Decimal("2.00"),
        high_return_pct=Decimal("100"),
        current_price=Decimal("1.79"),
        elapsed_seconds=60,
    )
    fast_180 = policy.momentum_drawdown(
        high_price=Decimal("2.00"),
        high_return_pct=Decimal("100"),
        current_price=Decimal("1.69"),
        elapsed_seconds=180,
    )
    slow = policy.momentum_drawdown(
        high_price=Decimal("2.36"),
        high_return_pct=Decimal("136"),
        current_price=Decimal("2.10"),
        elapsed_seconds=20 * 60,
    )
    below_activation = policy.momentum_drawdown(
        high_price=Decimal("1.49"),
        high_return_pct=Decimal("49"),
        current_price=Decimal("1.20"),
        elapsed_seconds=20,
    )

    assert fast_60 is not None and fast_60[0] >= Decimal("10")
    assert fast_180 is not None and fast_180[0] >= Decimal("15")
    assert slow is None
    assert below_activation is None
