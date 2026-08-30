"""add entitlement membership, Stripe price catalog, and risk acknowledgement

Revision ID: 20260830_0015
Revises: 20260830_0014
Create Date: 2026-08-30
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0015"
down_revision: str | None = "20260830_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_type", sa.String(24), nullable=False),
        sa.Column("pricing_version", sa.String(40), nullable=False),
        sa.Column("stripe_product_id", sa.String(255), nullable=True),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("unit_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("billing_interval", sa.String(16), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "plan_type IN ('DAY_PASS','MONTHLY')",
            name=op.f("ck_membership_prices_membership_price_plan"),
        ),
        sa.CheckConstraint(
            "unit_amount >= 0",
            name=op.f("ck_membership_prices_membership_price_amount_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_prices")),
        sa.UniqueConstraint("plan_type", "pricing_version", name="membership_price_version"),
        sa.UniqueConstraint("stripe_price_id", name="membership_stripe_price"),
    )
    op.create_index(op.f("ix_membership_prices_plan_type"), "membership_prices", ["plan_type"])
    price_table = sa.table(
        "membership_prices",
        sa.column("id", sa.Uuid()),
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
                "id": uuid.UUID("00000000-0000-4000-8000-000000000101"),
                "plan_type": "DAY_PASS",
                "pricing_version": "DAY_PASS_V1",
                "unit_amount": 999,
                "currency": "usd",
                "billing_interval": None,
                "is_current": True,
                "is_active": True,
            },
            {
                "id": uuid.UUID("00000000-0000-4000-8000-000000000102"),
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

    op.create_table(
        "membership_acknowledgements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("document_type", sa.String(24), nullable=False),
        sa.Column("document_version", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discord_interaction_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "document_type IN ('RISK_DISCLOSURE','TERMS','PRIVACY')",
            name=op.f("ck_membership_acknowledgements_membership_acknowledgement_document_type"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_membership_acknowledgements_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_acknowledgements")),
        sa.UniqueConstraint(
            "discord_user_id",
            "document_type",
            "document_version",
            name="membership_acknowledgement_once",
        ),
    )
    op.create_index(
        op.f("ix_membership_acknowledgements_guild_id"), "membership_acknowledgements", ["guild_id"]
    )
    op.create_index(
        op.f("ix_membership_acknowledgements_discord_user_id"),
        "membership_acknowledgements",
        ["discord_user_id"],
    )

    op.create_table(
        "membership_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("entitlement_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_trading_day", sa.Date(), nullable=True),
        sa.Column("last_trading_day", sa.Date(), nullable=True),
        sa.Column("membership_price_id", sa.Uuid(), nullable=True),
        sa.Column("pricing_version", sa.String(40), nullable=True),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("unit_amount_at_signup", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("provider_customer_id", sa.String(255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(255), nullable=True),
        sa.Column("provider_checkout_session_id", sa.String(255), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("source_entitlement_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("extension_type", sa.String(24), nullable=True),
        sa.Column("extension_amount", sa.Integer(), nullable=True),
        sa.Column("old_effective_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_effective_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entitlement_type IN "
            "('FREE_TRIAL','DAY_PASS','MONTHLY','GIFT','MANUAL','MANUAL_EXTENSION')",
            name=op.f("ck_membership_entitlements_entitlement_type"),
        ),
        sa.CheckConstraint(
            "status IN "
            "('ACTIVE','PAST_DUE','CANCEL_AT_PERIOD_END','EXPIRED','CANCELLED','REVOKED')",
            name=op.f("ck_membership_entitlements_entitlement_status"),
        ),
        sa.CheckConstraint(
            "unit_amount_at_signup IS NULL OR unit_amount_at_signup >= 0",
            name=op.f("ck_membership_entitlements_entitlement_amount_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_membership_entitlements_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_price_id"],
            ["membership_prices.id"],
            name=op.f("fk_membership_entitlements_membership_price_id_membership_prices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_entitlement_id"],
            ["membership_entitlements.id"],
            name=op.f("fk_membership_entitlements_source_entitlement_id_membership_entitlements"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_entitlements")),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="entitlement_provider_subscription"
        ),
        sa.UniqueConstraint(
            "provider", "provider_checkout_session_id", name="entitlement_provider_checkout"
        ),
    )
    for name in (
        "guild_id",
        "discord_user_id",
        "status",
        "ends_at",
        "membership_price_id",
        "provider_customer_id",
        "provider_subscription_id",
        "provider_checkout_session_id",
        "source_entitlement_id",
    ):
        op.create_index(
            op.f(f"ix_membership_entitlements_{name}"), "membership_entitlements", [name]
        )
    op.create_index(
        "ix_entitlements_user_status",
        "membership_entitlements",
        ["guild_id", "discord_user_id", "status"],
    )

    op.create_table(
        "membership_trials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("trial_type", sa.String(24), nullable=False),
        sa.Column("trading_days_granted", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_trading_day", sa.Date(), nullable=False),
        sa.Column("last_trading_day", sa.Date(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("entitlement_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trading_days_granted > 0",
            name=op.f("ck_membership_trials_membership_trial_days_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_membership_trials_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_id"],
            ["membership_entitlements.id"],
            name=op.f("fk_membership_trials_entitlement_id_membership_entitlements"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_trials")),
        sa.UniqueConstraint("discord_user_id", "trial_type", name="membership_trial_lifetime_once"),
        sa.UniqueConstraint("entitlement_id", name=op.f("uq_membership_trials_entitlement_id")),
    )
    op.create_index(op.f("ix_membership_trials_guild_id"), "membership_trials", ["guild_id"])
    op.create_index(
        op.f("ix_membership_trials_discord_user_id"), "membership_trials", ["discord_user_id"]
    )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=True),
        sa.Column("membership_id", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_status", sa.String(24), nullable=False),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership_entitlements.id"],
            name=op.f("fk_payment_events_membership_id_membership_entitlements"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_events")),
        sa.UniqueConstraint("provider", "provider_event_id", name="payment_event_provider_id"),
    )
    op.create_index(
        op.f("ix_payment_events_discord_user_id"), "payment_events", ["discord_user_id"]
    )
    op.create_index(op.f("ix_payment_events_membership_id"), "payment_events", ["membership_id"])
    op.create_index(
        "ix_payment_events_user_created", "payment_events", ["discord_user_id", "created_at"]
    )

    op.add_column("membership_sessions", sa.Column("membership_type", sa.String(24), nullable=True))
    op.add_column("membership_sessions", sa.Column("pricing_version", sa.String(40), nullable=True))
    op.add_column("membership_sessions", sa.Column("membership_price_id", sa.Uuid(), nullable=True))
    op.add_column(
        "membership_sessions",
        sa.Column("provider_checkout_session_id", sa.String(255), nullable=True),
    )
    op.add_column("membership_sessions", sa.Column("checkout_url", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_membership_sessions_membership_price_id_membership_prices"),
        "membership_sessions",
        "membership_prices",
        ["membership_price_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_membership_sessions_membership_price_id"),
        "membership_sessions",
        ["membership_price_id"],
    )
    op.create_unique_constraint(
        op.f("uq_membership_sessions_provider_checkout_session_id"),
        "membership_sessions",
        ["provider_checkout_session_id"],
    )

    # Preserve every pre-v2 access record as an independent entitlement. The old
    # aggregate table remains for rollback and historical audit only.
    op.execute(
        sa.text("""
        INSERT INTO membership_entitlements (
            id, guild_id, discord_user_id, entitlement_type, status, starts_at, ends_at,
            provider, provider_customer_id, provider_subscription_id,
            cancel_at_period_end, granted_by_user_id, version, created_at, updated_at
        )
        SELECT id, guild_id, discord_user_id,
            CASE WHEN source = 'GIFT' THEN 'GIFT' ELSE 'MANUAL' END,
            CASE
                WHEN status = 'REMOVED' THEN 'REVOKED'
                WHEN status = 'CANCELLED' THEN 'CANCELLED'
                ELSE status
            END,
            starts_at, ends_at, provider, provider_customer_id, provider_subscription_id,
            cancel_at_period_end, created_by, version, created_at, updated_at
        FROM memberships
        ON CONFLICT (id) DO NOTHING
    """)
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_membership_sessions_provider_checkout_session_id"),
        "membership_sessions",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_membership_sessions_membership_price_id"), table_name="membership_sessions"
    )
    op.drop_constraint(
        op.f("fk_membership_sessions_membership_price_id_membership_prices"),
        "membership_sessions",
        type_="foreignkey",
    )
    for name in (
        "checkout_url",
        "provider_checkout_session_id",
        "membership_price_id",
        "pricing_version",
        "membership_type",
    ):
        op.drop_column("membership_sessions", name)
    op.drop_index("ix_payment_events_user_created", table_name="payment_events")
    op.drop_index(op.f("ix_payment_events_membership_id"), table_name="payment_events")
    op.drop_index(op.f("ix_payment_events_discord_user_id"), table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index(op.f("ix_membership_trials_discord_user_id"), table_name="membership_trials")
    op.drop_index(op.f("ix_membership_trials_guild_id"), table_name="membership_trials")
    op.drop_table("membership_trials")
    op.drop_index("ix_entitlements_user_status", table_name="membership_entitlements")
    for name in reversed(
        (
            "guild_id",
            "discord_user_id",
            "status",
            "ends_at",
            "membership_price_id",
            "provider_customer_id",
            "provider_subscription_id",
            "provider_checkout_session_id",
            "source_entitlement_id",
        )
    ):
        op.drop_index(
            op.f(f"ix_membership_entitlements_{name}"), table_name="membership_entitlements"
        )
    op.drop_table("membership_entitlements")
    op.drop_index(
        op.f("ix_membership_acknowledgements_discord_user_id"),
        table_name="membership_acknowledgements",
    )
    op.drop_index(
        op.f("ix_membership_acknowledgements_guild_id"), table_name="membership_acknowledgements"
    )
    op.drop_table("membership_acknowledgements")
    op.drop_index(op.f("ix_membership_prices_plan_type"), table_name="membership_prices")
    op.drop_table("membership_prices")
