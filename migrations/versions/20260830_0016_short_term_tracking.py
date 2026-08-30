"""add independent Short-Term tracking lifecycle

Revision ID: 20260830_0016
Revises: 20260830_0015
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0016"
down_revision: str | None = "20260830_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_config", sa.Column("short_term_notice_message_id", sa.BigInteger()))
    op.alter_column("trades", "mentor_id", existing_type=sa.Uuid(), nullable=True)

    op.create_table(
        "short_term_tracking",
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
        sa.Column("milestones_hit", sa.JSON(), nullable=False),
        sa.Column("momentum_tp_events", sa.JSON(), nullable=False),
        sa.Column("reference_protection_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("reference_protection_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("reference_protection_reason", sa.String(64), nullable=False),
        sa.Column("tracking_state", sa.String(24), nullable=False),
        sa.Column("tracking_end_reason", sa.String(64)),
        sa.Column("tracking_end_price", sa.Numeric(18, 4)),
        sa.Column("tracking_end_return_pct", sa.Numeric(12, 4)),
        sa.Column("tracking_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tracking_ended_at", sa.DateTime(timezone=True)),
        sa.Column("overnight_count", sa.Integer(), nullable=False),
        sa.Column("last_session_date", sa.Date()),
        sa.Column("closing_price", sa.Numeric(18, 4)),
        sa.Column("closing_return_pct", sa.Numeric(12, 4)),
        sa.Column("last_quote_at", sa.DateTime(timezone=True)),
        sa.Column("tracking_policy_version", sa.String(40), nullable=False),
        sa.Column("price_source", sa.String(8), nullable=False),
        sa.Column("momentum_anchor_version", sa.Integer(), nullable=False),
        sa.Column("momentum_last_event_anchor_version", sa.Integer(), nullable=False),
        sa.Column("momentum_cooldown_until", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint("entry_price > 0", name="short_term_tracking_entry_positive"),
        sa.CheckConstraint(
            "overnight_count >= 0", name="short_term_tracking_overnight_nonnegative"
        ),
        sa.CheckConstraint("price_source IN ('BID','MID','LAST')", name="short_term_price_source"),
        sa.CheckConstraint(
            "tracking_state IN ('ACTIVE','OVERNIGHT_ACTIVE','STOPPED')",
            name="short_term_tracking_state",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="short_term_tracking_trade"),
    )
    op.create_index("ix_short_term_tracking_guild_id", "short_term_tracking", ["guild_id"])
    op.create_index("ix_short_term_tracking_trade_id", "short_term_tracking", ["trade_id"])
    op.create_index(
        "ix_short_term_tracking_tracking_ended_at", "short_term_tracking", ["tracking_ended_at"]
    )
    op.create_index(
        "ix_short_term_tracking_guild_state",
        "short_term_tracking",
        ["guild_id", "tracking_state"],
    )

    op.create_table(
        "short_term_tracking_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("milestone_pct", sa.Integer()),
        sa.Column("source_market_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("high_watermark_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("high_watermark_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("high_watermark_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("low_watermark_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("low_watermark_return_pct", sa.Numeric(12, 4), nullable=False),
        sa.Column("reference_protection_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("trigger_market_price", sa.Numeric(18, 4)),
        sa.Column("trigger_market_return_pct", sa.Numeric(12, 4)),
        sa.Column("drawdown_pct", sa.Numeric(12, 4)),
        sa.Column("drawdown_duration_seconds", sa.Integer()),
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
            "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT','RUNNER_MILESTONE',"
            "'FAST_MOMENTUM_REVERSAL','REFERENCE_PROTECTION_MOVED','TRACKING_STOPPED',"
            "'OVERNIGHT_CARRY','OVERNIGHT_GAP_STOP')",
            name="short_term_event_type",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_id"], ["short_term_tracking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tracking_id", "event_key", name="short_term_tracking_event_key"),
        sa.UniqueConstraint("guild_id", "public_ref", name="short_term_event_public_ref"),
        sa.UniqueConstraint("guild_id", "discord_message_id", name="short_term_event_message"),
    )
    for name in ("guild_id", "tracking_id", "trade_id"):
        op.create_index(
            f"ix_short_term_tracking_events_{name}", "short_term_tracking_events", [name]
        )
    op.create_index(
        "ix_short_term_events_public_queue",
        "short_term_tracking_events",
        ["guild_id", "public_notification", "published_at"],
    )

    op.create_table(
        "short_term_daily_snapshots",
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
        sa.Column("reference_protection_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("tracking_state", sa.String(24), nullable=False),
        sa.Column("tracking_end_reason", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracking_id"], ["short_term_tracking.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tracking_id", "session_date", name="short_term_daily_tracking_session"
        ),
    )
    for name in ("guild_id", "tracking_id", "trade_id"):
        op.create_index(
            f"ix_short_term_daily_snapshots_{name}", "short_term_daily_snapshots", [name]
        )
    op.create_index(
        "ix_short_term_daily_guild_session",
        "short_term_daily_snapshots",
        ["guild_id", "session_date"],
    )

    op.create_table(
        "daily_results_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("public_ref", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
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
            "status IN ('PENDING','PUBLISHED','FAILED')", name="daily_results_status"
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "session_date", name="daily_results_guild_session"),
        sa.UniqueConstraint("guild_id", "message_id", name="daily_results_message"),
    )
    op.create_index(
        "ix_daily_results_publications_guild_id", "daily_results_publications", ["guild_id"]
    )
    op.create_index(
        "ix_daily_results_publications_session_date", "daily_results_publications", ["session_date"]
    )


def downgrade() -> None:
    op.drop_table("daily_results_publications")
    op.drop_table("short_term_daily_snapshots")
    op.drop_table("short_term_tracking_events")
    op.drop_table("short_term_tracking")
    op.alter_column("trades", "mentor_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("guild_config", "short_term_notice_message_id")
