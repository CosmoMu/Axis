"""separate calendar-day Free Trial duration from trading-day access

Revision ID: 20260831_0025
Revises: 20260831_0024
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0025"
down_revision: str | None = "20260831_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("membership_trials", sa.Column("duration_unit", sa.String(24)))
    op.add_column("membership_trials", sa.Column("duration_amount", sa.Integer()))
    op.add_column("membership_trials", sa.Column("calendar_days_granted", sa.Integer()))
    op.add_column("membership_trials", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column(
        "membership_trials",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # Existing claims retain their exact timestamps and historical trading-day semantics.
    op.execute(
        "UPDATE membership_trials "
        "SET duration_unit='TRADING_DAY', "
        "duration_amount=trading_days_granted, started_at=claimed_at"
    )
    op.alter_column("membership_trials", "duration_unit", nullable=False)
    op.alter_column("membership_trials", "duration_amount", nullable=False)
    op.alter_column("membership_trials", "started_at", nullable=False)
    op.alter_column("membership_trials", "trading_days_granted", nullable=True)
    op.alter_column("membership_trials", "first_trading_day", nullable=True)
    op.alter_column("membership_trials", "last_trading_day", nullable=True)

    op.drop_constraint(
        op.f("ck_membership_trials_membership_trial_days_positive"),
        "membership_trials",
        type_="check",
    )
    op.create_check_constraint(
        "membership_trial_duration_unit",
        "membership_trials",
        "duration_unit IN ('CALENDAR_DAY','TRADING_DAY')",
    )
    op.create_check_constraint(
        "membership_trial_duration_positive",
        "membership_trials",
        "duration_amount > 0",
    )
    op.create_check_constraint(
        "membership_trial_trading_days_positive",
        "membership_trials",
        "trading_days_granted IS NULL OR trading_days_granted > 0",
    )
    op.create_check_constraint(
        "membership_trial_calendar_days_positive",
        "membership_trials",
        "calendar_days_granted IS NULL OR calendar_days_granted > 0",
    )


def downgrade() -> None:
    # A downgrade has no calendar-day representation. Preserve the claim as a positive
    # legacy row without changing its entitlement expiry.
    op.execute(
        "UPDATE membership_trials SET "
        "trading_days_granted=COALESCE(trading_days_granted, duration_amount), "
        "first_trading_day=COALESCE(first_trading_day, CAST(claimed_at AS DATE)), "
        "last_trading_day=COALESCE(last_trading_day, CAST(claimed_at AS DATE))"
    )
    for name in (
        "membership_trial_calendar_days_positive",
        "membership_trial_trading_days_positive",
        "membership_trial_duration_positive",
        "membership_trial_duration_unit",
    ):
        op.drop_constraint(op.f(f"ck_membership_trials_{name}"), "membership_trials", type_="check")
    op.create_check_constraint(
        "membership_trial_days_positive",
        "membership_trials",
        "trading_days_granted > 0",
    )
    op.alter_column("membership_trials", "last_trading_day", nullable=False)
    op.alter_column("membership_trials", "first_trading_day", nullable=False)
    op.alter_column("membership_trials", "trading_days_granted", nullable=False)
    op.drop_column("membership_trials", "updated_at")
    op.drop_column("membership_trials", "started_at")
    op.drop_column("membership_trials", "calendar_days_granted")
    op.drop_column("membership_trials", "duration_amount")
    op.drop_column("membership_trials", "duration_unit")
