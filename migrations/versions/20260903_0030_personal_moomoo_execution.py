"""add Owner-only personal Moomoo execution domain

Revision ID: 20260903_0030
Revises: 20260903_0029
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0030"
down_revision: str | None = "20260903_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_config", sa.Column("moomoo_trading_channel_id", sa.BigInteger()))
    op.add_column("guild_config", sa.Column("moomoo_panel_message_id", sa.BigInteger()))

    op.create_table(
        "personal_execution_settings",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("account_ref", sa.String(32)),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("broker_environment", sa.String(16), nullable=False),
        sa.Column("auto_follow_enabled", sa.Boolean(), nullable=False),
        sa.Column("follow_scope", sa.String(32), nullable=False),
        sa.Column("manual_position_sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_risk_management_enabled", sa.Boolean(), nullable=False),
        sa.Column("pause_new_entries", sa.Boolean(), nullable=False),
        sa.Column("pause_auto_management", sa.Boolean(), nullable=False),
        sa.Column("entry_max_chase_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("position_equity_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("position_budget_min", sa.Numeric(18, 2), nullable=False),
        sa.Column("position_budget_max", sa.Numeric(18, 2), nullable=False),
        sa.Column("trailing_stop_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("max_quote_age_seconds", sa.Integer(), nullable=False),
        sa.Column("max_bid_ask_spread_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("minimum_option_volume", sa.Integer()),
        sa.Column("minimum_open_interest", sa.Integer()),
        sa.Column("liquidity_guard_mode", sa.String(16), nullable=False),
        sa.Column("short_term_entry_ttl_minutes", sa.Integer(), nullable=False),
        sa.Column("swing_entry_ttl_minutes", sa.Integer(), nullable=False),
        sa.Column("market_open_guard_enabled", sa.Boolean(), nullable=False),
        sa.Column("market_open_guard_minutes", sa.Integer(), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.BigInteger()),
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
            "execution_mode IN ('DRY_RUN','LIVE')", name="personal_execution_mode"
        ),
        sa.CheckConstraint(
            "broker_environment IN ('SIMULATE','REAL')", name="personal_broker_environment"
        ),
        sa.CheckConstraint(
            "follow_scope IN ('OWNER_ONLY','ALL_ELIGIBLE_SIGNALS')",
            name="personal_follow_scope",
        ),
        sa.CheckConstraint(
            "entry_max_chase_pct >= 0", name="personal_entry_chase_nonnegative"
        ),
        sa.CheckConstraint(
            "position_equity_pct > 0 AND position_equity_pct <= 1",
            name="personal_equity_pct",
        ),
        sa.CheckConstraint(
            "position_budget_min > 0 AND position_budget_max >= position_budget_min",
            name="personal_budget_range",
        ),
        sa.CheckConstraint(
            "trailing_stop_pct > 0 AND trailing_stop_pct < 1",
            name="personal_trailing_pct",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "personal_positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("contract_key", sa.String(80), nullable=False),
        sa.Column("broker_contract_code", sa.String(80), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(18, 4), nullable=False),
        sa.Column("option_side", sa.String(8), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("linked_trade_id", sa.Uuid()),
        sa.Column("linked_publication_id", sa.Uuid()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("original_managed_quantity", sa.Integer(), nullable=False),
        sa.Column("average_cost", sa.Numeric(18, 4)),
        sa.Column("total_cost_basis", sa.Numeric(18, 2)),
        sa.Column("current_price", sa.Numeric(18, 4)),
        sa.Column("current_return_pct", sa.Numeric(12, 4)),
        sa.Column("lifetime_high_price", sa.Numeric(18, 4)),
        sa.Column("risk_high_watermark", sa.Numeric(18, 4)),
        sa.Column("risk_stage", sa.String(16), nullable=False),
        sa.Column("protection_reference", sa.Numeric(18, 4)),
        sa.Column("risk_epoch_number", sa.Integer(), nullable=False),
        sa.Column("tp50_executed", sa.Boolean(), nullable=False),
        sa.Column("tp100_executed", sa.Boolean(), nullable=False),
        sa.Column("opening_guard_last_active", sa.Boolean(), nullable=False),
        sa.Column("last_quote_at", sa.DateTime(timezone=True)),
        sa.Column("last_broker_sync_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
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
            "source IN ('AXIS_AUTO','MANUAL_MOOMOO','AXIS_AUTO_MANUAL_ADD')",
            name="personal_position_source",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_ENTRY','PARTIALLY_FILLED','ACTIVE',"
            "'BREAKEVEN_PROTECTED','TRAILING','RUNNER','PAUSED','CLOSED',"
            "'CLOSED_MANUAL','ENTRY_EXPIRED','CANCELLED_ENTRY','BROKER_REJECTED','SYNC_ERROR')",
            name="personal_position_status",
        ),
        sa.CheckConstraint(
            "risk_stage IN ('INITIAL','BREAKEVEN','TRAILING','RUNNER','PAUSED')",
            name="personal_risk_stage",
        ),
        sa.CheckConstraint("quantity >= 0", name="personal_position_quantity"),
        sa.CheckConstraint(
            "original_managed_quantity >= 0", name="personal_original_quantity"
        ),
        sa.CheckConstraint("risk_epoch_number >= 1", name="personal_risk_epoch_positive"),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_trade_id"], ["trades.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["linked_publication_id"], ["trade_publications.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_positions_guild_id", "personal_positions", ["guild_id"])
    op.create_index(
        "ix_personal_positions_linked_trade_id",
        "personal_positions",
        ["linked_trade_id"],
    )
    op.create_index(
        "ix_personal_positions_linked_publication_id",
        "personal_positions",
        ["linked_publication_id"],
    )
    op.create_index(
        "ix_personal_positions_active", "personal_positions", ["guild_id", "account_ref", "status"]
    )
    op.create_index(
        "ix_personal_positions_contract",
        "personal_positions",
        ["guild_id", "account_ref", "contract_key"],
    )

    op.create_table(
        "personal_position_risk_epochs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("personal_position_id", sa.Uuid(), nullable=False),
        sa.Column("epoch_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starting_quantity", sa.Integer(), nullable=False),
        sa.Column("average_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("risk_high_watermark", sa.Numeric(18, 4), nullable=False),
        sa.Column("risk_stage", sa.String(16), nullable=False),
        sa.Column("protection_reference", sa.Numeric(18, 4)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("epoch_number >= 1", name="personal_epoch_number_positive"),
        sa.ForeignKeyConstraint(
            ["personal_position_id"], ["personal_positions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("personal_position_id", "epoch_number", name="personal_risk_epoch"),
    )
    op.create_index(
        "ix_personal_position_risk_epochs_personal_position_id",
        "personal_position_risk_epochs",
        ["personal_position_id"],
    )

    op.create_table(
        "personal_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_position_id", sa.Uuid()),
        sa.Column("linked_trade_id", sa.Uuid()),
        sa.Column("linked_publication_id", sa.Uuid()),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("contract_key", sa.String(80), nullable=False),
        sa.Column("broker_contract_code", sa.String(80), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("broker_environment", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("broker_order_id", sa.String(128)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("average_fill_price", sa.Numeric(18, 4)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.Column("last_broker_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("axis_owned", sa.Boolean(), nullable=False),
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
            "purpose IN ('ENTRY','TP50','TP100','STOP_EXIT','TRAILING_EXIT','SWING_CLOSE_EXIT')",
            name="personal_order_purpose",
        ),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="personal_order_side"),
        sa.CheckConstraint("order_type = 'LIMIT'", name="personal_order_limit_only"),
        sa.CheckConstraint(
            "status IN ('DRY_RUN_VALIDATED','PENDING','SUBMITTED','PARTIALLY_FILLED','FILLED',"
            "'CANCELLED','REJECTED','EXPIRED','FAILED')",
            name="personal_order_status",
        ),
        sa.CheckConstraint("quantity > 0", name="personal_order_quantity"),
        sa.CheckConstraint("filled_quantity >= 0", name="personal_filled_quantity"),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["personal_position_id"], ["personal_positions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["linked_trade_id"], ["trades.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["linked_publication_id"], ["trade_publications.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="personal_order_idempotency"),
        sa.UniqueConstraint("account_ref", "broker_order_id", name="personal_broker_order"),
    )
    for name in ("guild_id", "personal_position_id", "linked_trade_id", "linked_publication_id"):
        op.create_index(f"ix_personal_orders_{name}", "personal_orders", [name])
    op.create_index(
        "ix_personal_orders_active", "personal_orders", ["guild_id", "status", "expires_at"]
    )

    op.create_table(
        "personal_fills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_position_id", sa.Uuid()),
        sa.Column("personal_order_id", sa.Uuid()),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("broker_fill_id", sa.String(128), nullable=False),
        sa.Column("contract_key", sa.String(80), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 2)),
        sa.Column("realized_return_pct", sa.Numeric(12, 4)),
        sa.Column("remaining_quantity", sa.Integer()),
        sa.Column("account_equity", sa.Numeric(18, 2)),
        sa.Column("execution_source", sa.String(32), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="personal_fill_side"),
        sa.CheckConstraint("quantity > 0", name="personal_fill_quantity"),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["personal_position_id"], ["personal_positions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["personal_order_id"], ["personal_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_ref", "broker_fill_id", name="personal_broker_fill"),
    )
    for name in ("guild_id", "personal_position_id", "personal_order_id"):
        op.create_index(f"ix_personal_fills_{name}", "personal_fills", [name])
    op.create_index(
        "ix_personal_fills_guild_executed", "personal_fills", ["guild_id", "executed_at"]
    )

    op.create_table(
        "personal_execution_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("personal_position_id", sa.Uuid()),
        sa.Column("personal_order_id", sa.Uuid()),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["personal_position_id"], ["personal_positions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["personal_order_id"], ["personal_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="personal_execution_event_key"),
    )
    for name in ("guild_id", "personal_position_id", "personal_order_id"):
        op.create_index(f"ix_personal_execution_events_{name}", "personal_execution_events", [name])
    op.create_index(
        "ix_personal_events_notify",
        "personal_execution_events",
        ["guild_id", "notified_at", "created_at"],
    )

    op.create_table(
        "personal_account_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("account_ref", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("account_equity", sa.Numeric(18, 2)),
        sa.Column("available_buying_power", sa.Numeric(18, 2)),
        sa.Column("cash", sa.Numeric(18, 2)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_account_snapshots_guild_id",
        "personal_account_snapshots",
        ["guild_id"],
    )
    op.create_index(
        "ix_personal_account_snapshot_time",
        "personal_account_snapshots",
        ["guild_id", "captured_at"],
    )

    op.create_table(
        "personal_daily_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("discord_message_id", sa.BigInteger()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PUBLISHED','FAILED')", name="personal_daily_summary_status"
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "session_date", name="personal_daily_summary_session"),
    )
    op.create_index(
        "ix_personal_daily_summaries_guild_id",
        "personal_daily_summaries",
        ["guild_id"],
    )
    op.create_index(
        "ix_personal_daily_summaries_session_date",
        "personal_daily_summaries",
        ["session_date"],
    )


def downgrade() -> None:
    op.drop_table("personal_daily_summaries")
    op.drop_table("personal_account_snapshots")
    op.drop_table("personal_execution_events")
    op.drop_table("personal_fills")
    op.drop_table("personal_orders")
    op.drop_table("personal_position_risk_epochs")
    op.drop_table("personal_positions")
    op.drop_table("personal_execution_settings")
    op.drop_column("guild_config", "moomoo_panel_message_id")
    op.drop_column("guild_config", "moomoo_trading_channel_id")
