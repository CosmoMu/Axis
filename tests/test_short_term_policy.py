from decimal import Decimal
from pathlib import Path

from app.services.short_term_policy import ShortTermTrackingPolicy

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "short_term_tracking.yaml"


def test_short_term_policy_has_exact_configured_milestones_and_mapping() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)

    assert policy.version == "ST_TRACKING_V1"
    assert policy.price_source == "MID"
    assert [(item.return_pct, item.card_type) for item in policy.milestones] == [
        (20, "TP"),
        (50, "TP"),
        (100, "RUNNER"),
        (150, "RUNNER"),
        (200, "RUNNER"),
        (300, "RUNNER"),
        (400, "RUNNER"),
        (500, "RUNNER"),
        (750, "RUNNER"),
        (1000, "RUNNER"),
    ]
    assert policy.crossed_milestones(Decimal("105"), {20, 50}) == tuple(
        item for item in policy.milestones if item.return_pct == 100
    )


def test_reference_protection_moves_to_previous_major_milestone() -> None:
    policy = ShortTermTrackingPolicy.load(POLICY_PATH)
    entry = Decimal("1.20")
    cases = (
        (set(), "0.60", -50),
        ({20}, "0.60", -50),
        ({20, 50}, "1.20", 0),
        ({20, 50, 100}, "1.80", 50),
        ({20, 50, 100, 150}, "2.40", 100),
        ({20, 50, 100, 150, 200}, "3.00", 150),
    )
    for hit, expected_price, expected_return in cases:
        price, return_pct = policy.reference_for(entry, hit)
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
