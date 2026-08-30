"""add general controls, payment membership, and system alerts

Revision ID: 20260830_0014
Revises: 20260830_0013
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0014"
down_revision: str | None = "20260830_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "welcome_channel_id",
        "subscriptions_channel_id",
        "lobby_channel_id",
        "member_wins_channel_id",
        "system_alerts_channel_id",
        "card_testing_channel_id",
        "welcome_message_id",
        "subscription_message_id",
        "results_guide_message_id",
        "lobby_guide_message_id",
        "member_wins_guide_message_id",
    ):
        op.add_column("guild_config", sa.Column(name, sa.BigInteger(), nullable=True))

    op.alter_column("memberships", "user_id", new_column_name="discord_user_id")
    op.execute(
        sa.text(
            "ALTER INDEX IF EXISTS ix_memberships_user_id RENAME TO ix_memberships_discord_user_id"
        )
    )
    op.add_column("memberships", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("memberships", sa.Column("provider_customer_id", sa.String(255), nullable=True))
    op.add_column(
        "memberships", sa.Column("provider_subscription_id", sa.String(255), nullable=True)
    )
    op.create_unique_constraint(
        "membership_provider_subscription",
        "memberships",
        ["provider", "provider_subscription_id"],
    )
    op.drop_constraint(
        op.f("ck_memberships_membership_status"),
        "memberships",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_memberships_membership_status"),
        "memberships",
        "status IN ('ACTIVE','PAST_DUE','CANCEL_AT_PERIOD_END','EXPIRED','CANCELLED','REMOVED')",
    )

    op.create_table(
        "membership_sessions",
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_membership_sessions_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_membership_sessions")),
    )
    op.create_index(
        op.f("ix_membership_sessions_guild_id"),
        "membership_sessions",
        ["guild_id"],
    )
    op.create_index(
        op.f("ix_membership_sessions_discord_user_id"),
        "membership_sessions",
        ["discord_user_id"],
    )
    op.create_index(
        op.f("ix_membership_sessions_expires_at"),
        "membership_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_membership_sessions_user_created",
        "membership_sessions",
        ["discord_user_id", "created_at"],
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("membership_session_id", sa.String(64), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["membership_session_id"],
            ["membership_sessions.session_id"],
            name=op.f("fk_payment_webhook_events_membership_session_id_membership_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_webhook_events")),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="payment_provider_event",
        ),
    )
    op.create_index(
        op.f("ix_payment_webhook_events_membership_session_id"),
        "payment_webhook_events",
        ["membership_session_id"],
    )
    op.create_index(
        "ix_payment_webhooks_received",
        "payment_webhook_events",
        ["received_at"],
    )

    op.create_table(
        "system_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("service", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("affected", sa.String(255), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name=op.f("ck_system_alerts_system_alert_occurrence_positive"),
        ),
        sa.CheckConstraint(
            "severity IN ('WARNING','ERROR')",
            name=op.f("ck_system_alerts_system_alert_severity"),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_config.guild_id"],
            name=op.f("fk_system_alerts_guild_id_guild_config"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_alerts")),
        sa.UniqueConstraint(
            "guild_id",
            "fingerprint",
            name="system_alert_fingerprint",
        ),
    )
    op.create_index(op.f("ix_system_alerts_guild_id"), "system_alerts", ["guild_id"])
    op.create_index(
        "ix_system_alerts_active",
        "system_alerts",
        ["guild_id", "resolved_at", "last_seen"],
    )


def downgrade() -> None:
    op.drop_index("ix_system_alerts_active", table_name="system_alerts")
    op.drop_index(op.f("ix_system_alerts_guild_id"), table_name="system_alerts")
    op.drop_table("system_alerts")
    op.drop_index("ix_payment_webhooks_received", table_name="payment_webhook_events")
    op.drop_index(
        op.f("ix_payment_webhook_events_membership_session_id"),
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")
    op.drop_index("ix_membership_sessions_user_created", table_name="membership_sessions")
    op.drop_index(op.f("ix_membership_sessions_expires_at"), table_name="membership_sessions")
    op.drop_index(
        op.f("ix_membership_sessions_discord_user_id"),
        table_name="membership_sessions",
    )
    op.drop_index(op.f("ix_membership_sessions_guild_id"), table_name="membership_sessions")
    op.drop_table("membership_sessions")
    op.drop_constraint(
        op.f("ck_memberships_membership_status"),
        "memberships",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_memberships_membership_status"),
        "memberships",
        "status IN ('ACTIVE','EXPIRED','CANCELLED','REMOVED')",
    )
    op.drop_constraint("membership_provider_subscription", "memberships", type_="unique")
    op.drop_column("memberships", "provider_subscription_id")
    op.drop_column("memberships", "provider_customer_id")
    op.drop_column("memberships", "provider")
    op.execute(
        sa.text(
            "ALTER INDEX IF EXISTS ix_memberships_discord_user_id RENAME TO ix_memberships_user_id"
        )
    )
    op.alter_column("memberships", "discord_user_id", new_column_name="user_id")
    for name in reversed(
        (
            "welcome_channel_id",
            "subscriptions_channel_id",
            "lobby_channel_id",
            "member_wins_channel_id",
            "system_alerts_channel_id",
            "card_testing_channel_id",
            "welcome_message_id",
            "subscription_message_id",
            "results_guide_message_id",
            "lobby_guide_message_id",
            "member_wins_guide_message_id",
        )
    ):
        op.drop_column("guild_config", name)
