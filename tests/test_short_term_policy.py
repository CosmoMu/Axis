from decimal import Decimal
from pathlib import Path

from app.services.short_term_policy import ShortTermTrackingPolicy

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"


def test_short_term_policy_has_exact_configured_tp_levels() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)

    assert policy.version == "ST_TRACKING_V2"
    assert policy.price_source == "MID"
    assert [(item.label, item.return_pct) for item in policy.tp_levels] == [
        ("TP1", 20),
        ("TP2", 50),
        ("TP3", 100),
        ("TP4", 150),
        ("TP5", 200),
        ("TP6", 300),
        ("TP7", 400),
        ("TP8", 500),
        ("TP9", 750),
        ("TP10", 1000),
    ]
    assert policy.crossed_tp_levels(Decimal("105"), {"TP1", "TP2"}) == tuple(
        item for item in policy.tp_levels if item.label == "TP3"
    )


def test_tracking_protection_locks_the_previous_tp_level() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)
    entry = Decimal("1.20")
    cases = (
        (set(), "0.60", -50),
        ({"TP1"}, "1.20", 0),
        ({"TP1", "TP2"}, "1.44", 20),
        ({"TP1", "TP2", "TP3"}, "1.80", 50),
        ({"TP1", "TP2", "TP3", "TP4"}, "2.40", 100),
        ({"TP1", "TP2", "TP3", "TP4", "TP5"}, "3.00", 150),
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
