"""add read-only market snapshots and daily summary publications

Revision ID: 20260829_0008
Revises: 20260829_0007
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0008"
down_revision: str | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("moomoo_option_code", sa.String(length=64), nullable=True))
    op.create_table(
        "market_quote_snapshots",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("last_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("market_state", sa.String(32), nullable=False),
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "last_price > 0", name=op.f("ck_market_quote_snapshots_market_quote_price_positive")
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", "session_date", name="market_quote_trade_session"),
    )
    op.create_index("ix_market_quote_snapshots_guild_id", "market_quote_snapshots", ["guild_id"])
    op.create_index("ix_market_quote_snapshots_trade_id", "market_quote_snapshots", ["trade_id"])
    op.create_index(
        "ix_market_quote_snapshots_session_date",
        "market_quote_snapshots",
        ["session_date"],
    )

    op.create_table(
        "daily_summary_publications",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("public_ref", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "category IN ('SHORT_TERM','SWING','LEAPS')",
            name=op.f("ck_daily_summary_publications_daily_summary_category"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PUBLISHED','FAILED')",
            name=op.f("ck_daily_summary_publications_daily_summary_status"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_daily_summary_publications_daily_summary_attempt_nonnegative"),
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "category",
            "session_date",
            name="daily_summary_guild_category_session",
        ),
        sa.UniqueConstraint("guild_id", "message_id", name="daily_summary_message"),
        sa.UniqueConstraint("guild_id", "public_ref", name="daily_summary_public_ref"),
    )
    op.create_index(
        "ix_daily_summary_publications_guild_id",
        "daily_summary_publications",
        ["guild_id"],
    )
    op.create_index(
        "ix_daily_summary_publications_session_date",
        "daily_summary_publications",
        ["session_date"],
    )


def downgrade() -> None:
    op.drop_table("daily_summary_publications")
    op.drop_table("market_quote_snapshots")
    op.drop_column("trades", "moomoo_option_code")
