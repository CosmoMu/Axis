"""isolate Stripe test and live payment domains

Revision ID: 20260831_0023
Revises: 20260830_0022
Create Date: 2026-08-31
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0023"
down_revision: str | None = "20260830_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "membership_prices",
        sa.Column("environment", sa.String(8), server_default="TEST", nullable=False),
    )
    op.create_index(
        op.f("ix_membership_prices_environment"), "membership_prices", ["environment"]
    )
    op.drop_constraint("membership_price_version", "membership_prices", type_="unique")
    op.drop_constraint("membership_stripe_price", "membership_prices", type_="unique")
    op.create_unique_constraint(
        "membership_price_environment_version",
        "membership_prices",
        ["environment", "plan_type", "pricing_version"],
    )
    op.create_unique_constraint(
        "membership_environment_stripe_price",
        "membership_prices",
        ["environment", "stripe_price_id"],
    )
    op.create_check_constraint(
        "ck_membership_prices_membership_price_environment",
        "membership_prices",
        "environment IN ('TEST','LIVE')",
    )

    price_table = sa.table(
        "membership_prices",
        sa.column("id", sa.Uuid()),
        sa.column("environment", sa.String()),
        sa.column("plan_type", sa.String()),
        sa.column("pricing_version", sa.String()),
        sa.column("unit_amount", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("billing_interval", sa.String()),
        sa.column("is_current", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        price_table,
        [
            {
                "id": uuid.UUID("00000000-0000-4000-8000-000000000201"),
                "environment": "LIVE",
                "plan_type": "DAY_PASS",
                "pricing_version": "DAY_PASS_V1",
                "unit_amount": 999,
                "currency": "usd",
                "billing_interval": None,
                "is_current": True,
                "is_active": True,
            },
            {
                "id": uuid.UUID("00000000-0000-4000-8000-000000000202"),
                "environment": "LIVE",
                "plan_type": "MONTHLY",
                "pricing_version": "MONTHLY_V1",
                "unit_amount": 9999,
                "currency": "usd",
                "billing_interval": "month",
                "is_current": True,
                "is_active": True,
            },
        ],
    )

    op.add_column(
        "membership_entitlements", sa.Column("payment_environment", sa.String(8), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE membership_entitlements SET payment_environment='TEST' "
            "WHERE provider='stripe' AND payment_environment IS NULL"
        )
    )
    op.create_index(
        op.f("ix_membership_entitlements_payment_environment"),
        "membership_entitlements",
        ["payment_environment"],
    )
    op.drop_constraint(
        "entitlement_provider_subscription", "membership_entitlements", type_="unique"
    )
    op.drop_constraint(
        "entitlement_provider_checkout", "membership_entitlements", type_="unique"
    )
    op.create_unique_constraint(
        "entitlement_provider_environment_subscription",
        "membership_entitlements",
        ["provider", "payment_environment", "provider_subscription_id"],
    )
    op.create_unique_constraint(
        "entitlement_provider_environment_checkout",
        "membership_entitlements",
        ["provider", "payment_environment", "provider_checkout_session_id"],
    )
    op.create_check_constraint(
        "ck_membership_entitlements_entitlement_payment_environment",
        "membership_entitlements",
        "payment_environment IS NULL OR payment_environment IN ('TEST','LIVE')",
    )

    op.add_column(
        "membership_sessions", sa.Column("payment_environment", sa.String(8), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE membership_sessions SET payment_environment='TEST' "
            "WHERE provider='stripe' AND payment_environment IS NULL"
        )
    )
    op.create_index(
        op.f("ix_membership_sessions_payment_environment"),
        "membership_sessions",
        ["payment_environment"],
    )
    op.drop_constraint(
        "uq_membership_sessions_provider_checkout_session_id",
        "membership_sessions",
        type_="unique",
    )
    op.create_unique_constraint(
        "membership_session_environment_checkout",
        "membership_sessions",
        ["provider", "payment_environment", "provider_checkout_session_id"],
    )
    op.create_check_constraint(
        "ck_membership_sessions_membership_session_payment_environment",
        "membership_sessions",
        "payment_environment IS NULL OR payment_environment IN ('TEST','LIVE')",
    )

    op.add_column(
        "payment_events",
        sa.Column("environment", sa.String(8), server_default="TEST", nullable=False),
    )
    op.create_index(op.f("ix_payment_events_environment"), "payment_events", ["environment"])
    op.drop_constraint("payment_event_provider_id", "payment_events", type_="unique")
    op.create_unique_constraint(
        "payment_event_environment_id",
        "payment_events",
        ["provider", "environment", "provider_event_id"],
    )
    op.create_check_constraint(
        "ck_payment_events_payment_event_environment",
        "payment_events",
        "environment IN ('TEST','LIVE')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_events_payment_event_environment", "payment_events", type_="check"
    )
    op.drop_constraint("payment_event_environment_id", "payment_events", type_="unique")
    op.create_unique_constraint(
        "payment_event_provider_id", "payment_events", ["provider", "provider_event_id"]
    )
    op.drop_index(op.f("ix_payment_events_environment"), table_name="payment_events")
    op.drop_column("payment_events", "environment")

    op.drop_constraint(
        "ck_membership_sessions_membership_session_payment_environment",
        "membership_sessions",
        type_="check",
    )
    op.drop_constraint(
        "membership_session_environment_checkout", "membership_sessions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_membership_sessions_provider_checkout_session_id",
        "membership_sessions",
        ["provider_checkout_session_id"],
    )
    op.drop_index(
        op.f("ix_membership_sessions_payment_environment"), table_name="membership_sessions"
    )
    op.drop_column("membership_sessions", "payment_environment")

    op.drop_constraint(
        "ck_membership_entitlements_entitlement_payment_environment",
        "membership_entitlements",
        type_="check",
    )
    op.drop_constraint(
        "entitlement_provider_environment_checkout", "membership_entitlements", type_="unique"
    )
    op.drop_constraint(
        "entitlement_provider_environment_subscription",
        "membership_entitlements",
        type_="unique",
    )
    op.create_unique_constraint(
        "entitlement_provider_subscription",
        "membership_entitlements",
        ["provider", "provider_subscription_id"],
    )
    op.create_unique_constraint(
        "entitlement_provider_checkout",
        "membership_entitlements",
        ["provider", "provider_checkout_session_id"],
    )
    op.drop_index(
        op.f("ix_membership_entitlements_payment_environment"),
        table_name="membership_entitlements",
    )
    op.drop_column("membership_entitlements", "payment_environment")

    op.execute(
        sa.text(
            "DELETE FROM membership_prices WHERE environment='LIVE' "
            "AND id IN ('00000000-0000-4000-8000-000000000201', "
            "'00000000-0000-4000-8000-000000000202')"
        )
    )
    op.drop_constraint(
        "ck_membership_prices_membership_price_environment", "membership_prices", type_="check"
    )
    op.drop_constraint(
        "membership_environment_stripe_price", "membership_prices", type_="unique"
    )
    op.drop_constraint(
        "membership_price_environment_version", "membership_prices", type_="unique"
    )
    op.create_unique_constraint(
        "membership_price_version", "membership_prices", ["plan_type", "pricing_version"]
    )
    op.create_unique_constraint(
        "membership_stripe_price", "membership_prices", ["stripe_price_id"]
    )
    op.drop_index(op.f("ix_membership_prices_environment"), table_name="membership_prices")
    op.drop_column("membership_prices", "environment")
