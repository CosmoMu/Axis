"""normalize Stripe environment check constraint names

Revision ID: 20260831_0024
Revises: 20260831_0023
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0024"
down_revision: str | None = "20260831_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CHECKS = (
    (
        "membership_prices",
        "ck_membership_prices_ck_membership_prices_membership_pr_017d",
        "membership_price_environment",
        "environment IN ('TEST','LIVE')",
    ),
    (
        "membership_entitlements",
        "ck_membership_entitlements_ck_membership_entitlements_e_a514",
        "entitlement_payment_environment",
        "payment_environment IS NULL OR payment_environment IN ('TEST','LIVE')",
    ),
    (
        "membership_sessions",
        "ck_membership_sessions_ck_membership_sessions_membershi_471f",
        "membership_session_payment_environment",
        "payment_environment IS NULL OR payment_environment IN ('TEST','LIVE')",
    ),
    (
        "payment_events",
        "ck_payment_events_ck_payment_events_payment_event_environment",
        "payment_event_environment",
        "environment IN ('TEST','LIVE')",
    ),
)


def upgrade() -> None:
    for table, legacy_name, normalized_name, condition in CHECKS:
        op.drop_constraint(op.f(legacy_name), table, type_="check")
        op.create_check_constraint(normalized_name, table, condition)


def downgrade() -> None:
    for table, _legacy_name, normalized_name, condition in reversed(CHECKS):
        op.drop_constraint(
            op.f(f"ck_{table}_{normalized_name}"),
            table,
            type_="check",
        )
        # Passing the previous fully-prefixed logical name recreates the
        # historical double-prefix through the project's naming convention.
        op.create_check_constraint(f"ck_{table}_{normalized_name}", table, condition)
