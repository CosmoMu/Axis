"""add simple tracked Swing V2 lifecycle

Revision ID: 20260903_0029
Revises: 20260902_0028
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0029"
down_revision: str | None = "20260902_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("tracking_mode", sa.String(32)))
    op.create_check_constraint(
        "trade_tracking_mode",
        "trades",
        "tracking_mode IS NULL OR tracking_mode IN ('LEGACY_SWING','SIMPLE_TRACKED_SWING')",
    )
    op.create_index("ix_trades_tracking_mode", "trades", ["tracking_mode"])
    # Every Swing that predates this revision remains on the legacy engine and UI.
    op.execute("UPDATE trades SET tracking_mode = 'LEGACY_SWING' WHERE category = 'SWING'")

    op.create_table(
        "swing_tracking",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("option_ticker", sa.String(64), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("current_return_pct", sa.Numeric(12, 4)),
        sa.Column("highest_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("highest_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("highest_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lowest_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("lowest_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("lowest_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tp_levels_hit", sa.JSON(), nullable=False),
        sa.Column("highest_tp_level", sa.String(16)),
        sa.Column("tracking_state", sa.String(16), nullable=False),
        sa.Column("tracking_end_reason", sa.String(64)),
        sa.Column("tracking_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tracking_ended_at", sa.DateTime(timezone=True)),
        sa.Column("last_session_date", sa.Date()),
        sa.Column("last_quote_at", sa.DateTime(timezone=True)),
        sa.Column("tracking_policy_version", sa.String(40), nullable=False),
        sa.Column("price_source", sa.String(8), nullable=False),
        sa.Column("close_requested_at", sa.DateTime(timezone=True)),
        sa.Column("close_reference_price", sa.Numeric(18, 4)),
        sa.Column("close_reference_return_pct", sa.Numeric(12, 4)),
        sa.Column("close_reference_source", sa.String(32)),
        sa.Column("consecutive_data_errors", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
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
        sa.CheckConstraint("entry_price > 0", name="swing_tracking_entry_positive"),
        sa.CheckConstraint("tracking_state IN ('ACTIVE','STOPPED')", name="swing_tracking_state"),
        sa.CheckConstraint("price_source IN ('BID','MID','LAST')", name="swing_price_source"),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="swing_tracking_trade"),
    )
    for name in ("guild_id", "trade_id", "tracking_ended_at"):
        op.create_index(f"ix_swing_tracking_{name}", "swing_tracking", [name])
    op.create_index(
        "ix_swing_tracking_guild_state", "swing_tracking", ["guild_id", "tracking_state"]
    )

    op.create_table(
        "swing_tracking_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("tp_return_pct", sa.Integer()),
        sa.Column("source_market_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("high_watermark_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("high_watermark_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("high_watermark_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("low_watermark_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("low_watermark_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("tracking_policy_version", sa.String(40), nullable=False),
        sa.Column("price_source", sa.String(8), nullable=False),
        sa.Column("public_notification", sa.Boolean(), nullable=False),
        sa.Column("public_card_type", sa.String(24)),
        sa.Column("public_price", sa.Numeric(18, 4)),
        sa.Column("public_return_pct", sa.Numeric(12, 4)),
        sa.Column("public_ref", sa.String(32)),
        sa.Column("discord_message_id", sa.BigInteger()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT',"
            "'MANUAL_SIGNAL_CLOSE','OPTION_EXPIRED')",
            name="swing_event_type",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_id"], ["swing_tracking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tracking_id", "event_key", name="swing_tracking_event_key"),
        sa.UniqueConstraint("guild_id", "public_ref", name="swing_event_public_ref"),
        sa.UniqueConstraint("guild_id", "discord_message_id", name="swing_event_message"),
    )
    for name in ("guild_id", "tracking_id", "trade_id"):
        op.create_index(f"ix_swing_tracking_events_{name}", "swing_tracking_events", [name])
    op.create_index(
        "ix_swing_events_public_queue",
        "swing_tracking_events",
        ["guild_id", "public_notification", "published_at"],
    )

    op.create_table(
        "swing_daily_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("closing_price", sa.Numeric(18, 4)),
        sa.Column("closing_return_pct", sa.Numeric(12, 4)),
        sa.Column("highest_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("highest_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("lowest_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("lowest_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("tracking_state", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_id"], ["swing_tracking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tracking_id", "session_date", name="swing_daily_tracking_session"),
    )
    for name in ("guild_id", "tracking_id", "trade_id"):
        op.create_index(f"ix_swing_daily_snapshots_{name}", "swing_daily_snapshots", [name])
    op.create_index(
        "ix_swing_daily_guild_session", "swing_daily_snapshots", ["guild_id", "session_date"]
    )


def downgrade() -> None:
    op.drop_table("swing_daily_snapshots")
    op.drop_table("swing_tracking_events")
    op.drop_table("swing_tracking")
    op.drop_index("ix_trades_tracking_mode", table_name="trades")
    op.drop_constraint("trade_tracking_mode", "trades", type_="check")
    op.drop_column("trades", "tracking_mode")
