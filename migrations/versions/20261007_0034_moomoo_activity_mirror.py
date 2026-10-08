"""add read-only Moomoo activity mirror

Revision ID: 20261007_0034
Revises: 20260913_0033
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0034"
down_revision: str | None = "20260913_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_config", sa.Column("one_k_challenge_channel_id", sa.BigInteger()))

    op.create_table(
        "moomoo_activity_states",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True)),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("latest_snapshot", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "moomoo_activity_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=False),
        sa.Column("instrument_code", sa.String(80), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 4)),
        sa.Column("average_fill_price", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("state_signature", sa.String(255), nullable=False),
        sa.Column("broker_updated_at", sa.DateTime(timezone=True)),
        sa.Column("notification_pending", sa.Boolean(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
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
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "account_ref", "broker_order_id", name="moomoo_activity_order"
        ),
    )
    op.create_index(
        "ix_moomoo_activity_order_pending",
        "moomoo_activity_orders",
        ["guild_id", "notification_pending"],
    )
    op.create_index(
        op.f("ix_moomoo_activity_orders_guild_id"),
        "moomoo_activity_orders",
        ["guild_id"],
    )

    op.create_table(
        "moomoo_activity_fills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("broker_fill_id", sa.String(128), nullable=False),
        sa.Column("broker_order_id", sa.String(128)),
        sa.Column("instrument_code", sa.String(80), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("fill_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "account_ref", "broker_fill_id", name="moomoo_activity_fill"
        ),
    )
    op.create_index(
        "ix_moomoo_activity_fill_pending",
        "moomoo_activity_fills",
        ["guild_id", "notified_at", "executed_at"],
    )
    op.create_index(
        op.f("ix_moomoo_activity_fills_guild_id"),
        "moomoo_activity_fills",
        ["guild_id"],
    )

    op.create_table(
        "moomoo_activity_daily_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("discord_message_ids", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "session_date", name="moomoo_activity_summary_session"
        ),
    )
    op.create_index(
        op.f("ix_moomoo_activity_daily_summaries_guild_id"),
        "moomoo_activity_daily_summaries",
        ["guild_id"],
    )
    op.create_index(
        op.f("ix_moomoo_activity_daily_summaries_session_date"),
        "moomoo_activity_daily_summaries",
        ["session_date"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_moomoo_activity_daily_summaries_session_date"),
        table_name="moomoo_activity_daily_summaries",
    )
    op.drop_index(
        op.f("ix_moomoo_activity_daily_summaries_guild_id"),
        table_name="moomoo_activity_daily_summaries",
    )
    op.drop_table("moomoo_activity_daily_summaries")
    op.drop_index(op.f("ix_moomoo_activity_fills_guild_id"), table_name="moomoo_activity_fills")
    op.drop_index("ix_moomoo_activity_fill_pending", table_name="moomoo_activity_fills")
    op.drop_table("moomoo_activity_fills")
    op.drop_index(op.f("ix_moomoo_activity_orders_guild_id"), table_name="moomoo_activity_orders")
    op.drop_index("ix_moomoo_activity_order_pending", table_name="moomoo_activity_orders")
    op.drop_table("moomoo_activity_orders")
    op.drop_table("moomoo_activity_states")
    op.drop_column("guild_config", "one_k_challenge_channel_id")
