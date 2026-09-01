"""add permanent newcomer approval gate and security records

Revision ID: 20260831_0026
Revises: 20260831_0025
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0026"
down_revision: str | None = "20260831_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_config", sa.Column("newcomer_role_id", sa.BigInteger()))
    op.add_column("guild_config", sa.Column("join_review_channel_id", sa.BigInteger()))
    op.add_column("guild_config", sa.Column("newcomer_status_message_id", sa.BigInteger()))
    op.add_column(
        "guild_config", sa.Column("newcomer_gate_activated_at", sa.DateTime(timezone=True))
    )

    op.create_table(
        "newcomer_profiles",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_username_snapshot", sa.String(100), nullable=False),
        sa.Column("discord_display_name_snapshot", sa.String(100), nullable=False),
        sa.Column("first_joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("join_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("role_sync_status", sa.String(16), nullable=False, server_default="SYNCED"),
        sa.Column("last_role_error", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("join_count >= 1", name="newcomer_profile_join_count_positive"),
        sa.CheckConstraint(
            "role_sync_status IN ('SYNCED','PENDING','FAILED')",
            name="newcomer_profile_role_sync_status",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "discord_user_id"),
    )
    op.create_index("ix_newcomer_profiles_approved_at", "newcomer_profiles", ["approved_at"])

    op.create_table(
        "access_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_username_snapshot", sa.String(100), nullable=False),
        sa.Column("discord_display_name_snapshot", sa.String(100), nullable=False),
        sa.Column("discovery_source", sa.String(32), nullable=False),
        sa.Column("referred_by_text", sa.String(200)),
        sa.Column("interests", sa.JSON(), nullable=False),
        sa.Column("risk_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("community_rules_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_user_id", sa.BigInteger()),
        sa.Column("review_note", sa.Text()),
        sa.Column("review_channel_id", sa.BigInteger()),
        sa.Column("review_message_id", sa.BigInteger()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','FLAGGED','APPROVED','REJECTED')",
            name="access_application_status",
        ),
        sa.CheckConstraint(
            "discovery_source IN "
            "('FRIEND_REFERRAL','X_SOCIAL_MEDIA','DISCORD','ONLINE_COMMUNITY','OTHER')",
            name="access_application_discovery_source",
        ),
        sa.CheckConstraint(
            "risk_acknowledged = TRUE AND community_rules_acknowledged = TRUE",
            name="access_application_agreements_required",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_applications_guild_id", "access_applications", ["guild_id"])
    op.create_index(
        "ix_access_applications_discord_user_id",
        "access_applications",
        ["discord_user_id"],
    )
    op.create_index("ix_access_applications_status", "access_applications", ["status"])
    op.create_index(
        "ix_access_applications_review",
        "access_applications",
        ["guild_id", "status", "submitted_at"],
    )
    op.create_index(
        "uq_access_application_open_per_user",
        "access_applications",
        ["guild_id", "discord_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','FLAGGED')"),
        sqlite_where=sa.text("status IN ('PENDING','FLAGGED')"),
    )
    op.create_index(
        "uq_access_application_approved_per_user",
        "access_applications",
        ["guild_id", "discord_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
        sqlite_where=sa.text("status = 'APPROVED'"),
    )

    op.create_table(
        "newcomer_risk_flags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("application_id", sa.Uuid()),
        sa.Column("risk_code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "severity IN ('LOW','MEDIUM','HIGH')", name="newcomer_risk_flag_severity"
        ),
        sa.CheckConstraint("occurrence_count >= 1", name="newcomer_risk_occurrence_positive"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["access_applications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "discord_user_id",
            "risk_code",
            name="newcomer_risk_flag_user_code",
        ),
    )
    op.create_index("ix_newcomer_risk_flags_guild_id", "newcomer_risk_flags", ["guild_id"])
    op.create_index(
        "ix_newcomer_risk_flags_discord_user_id",
        "newcomer_risk_flags",
        ["discord_user_id"],
    )
    op.create_index(
        "ix_newcomer_risk_flags_application_id",
        "newcomer_risk_flags",
        ["application_id"],
    )
    op.create_index(
        "ix_newcomer_risk_active",
        "newcomer_risk_flags",
        ["guild_id", "resolved_at", "severity"],
    )

    op.add_column("membership_trials", sa.Column("application_id", sa.Uuid()))
    op.add_column("membership_trials", sa.Column("approved_by_user_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_membership_trials_application_id_access_applications",
        "membership_trials",
        "access_applications",
        ["application_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_membership_trials_application_id", "membership_trials", ["application_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_membership_trials_application_id", "membership_trials", type_="unique")
    op.drop_constraint(
        "fk_membership_trials_application_id_access_applications",
        "membership_trials",
        type_="foreignkey",
    )
    op.drop_column("membership_trials", "approved_by_user_id")
    op.drop_column("membership_trials", "application_id")
    op.drop_table("newcomer_risk_flags")
    op.drop_table("access_applications")
    op.drop_table("newcomer_profiles")
    op.drop_column("guild_config", "newcomer_status_message_id")
    op.drop_column("guild_config", "newcomer_gate_activated_at")
    op.drop_column("guild_config", "join_review_channel_id")
    op.drop_column("guild_config", "newcomer_role_id")
