"""add manager-reviewed daily results workflow

Revision ID: 20260830_0022
Revises: 20260830_0021
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0022"
down_revision: str | None = "20260830_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_config",
        sa.Column("results_review_channel_id", sa.BigInteger()),
    )
    op.create_table(
        "daily_results_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("draft_snapshot", sa.JSON(), nullable=False),
        sa.Column("final_snapshot", sa.JSON()),
        sa.Column("display_overrides", sa.JSON(), nullable=False),
        sa.Column("scheduled_publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("discord_review_message_id", sa.BigInteger()),
        sa.Column("discord_public_message_id", sa.BigInteger()),
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
            "status IN ('DRAFT','REVIEWED','PUBLISHED','CORRECTED')",
            name="daily_results_review_status",
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "trading_date",
            name="daily_results_review_guild_date",
        ),
    )
    op.create_index(
        "ix_daily_results_reviews_guild_id",
        "daily_results_reviews",
        ["guild_id"],
    )
    op.create_index(
        "ix_daily_results_reviews_trading_date",
        "daily_results_reviews",
        ["trading_date"],
    )
    op.create_index(
        "ix_daily_results_reviews_due",
        "daily_results_reviews",
        ["status", "scheduled_publish_at"],
    )
    op.create_table(
        "daily_results_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("display_result_pct", sa.Numeric(12, 4)),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("excluded_by", sa.BigInteger()),
        sa.Column("excluded_at", sa.DateTime(timezone=True)),
        sa.Column("exclusion_reason", sa.String(40)),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("display_text_override", sa.Text()),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("original_result_pct", sa.Numeric(12, 4)),
        sa.Column("correction_reason", sa.Text()),
        sa.Column("corrected_by", sa.BigInteger()),
        sa.Column("corrected_at", sa.DateTime(timezone=True)),
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
            "category IN ('SHORT_TERM','SWING','LEAPS')",
            name="daily_results_item_category",
        ),
        sa.CheckConstraint(
            "exclusion_reason IS NULL OR exclusion_reason IN "
            "('DUPLICATE_SIGNAL','DATA_QUALITY_ISSUE','BAD_QUOTE','WRONG_CONTRACT',"
            "'MANUAL_CORRECTION','NOT_FOR_PUBLIC_SUMMARY','OTHER')",
            name="daily_results_item_exclusion_reason",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["daily_results_reviews.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "trade_id", name="daily_results_item_review_trade"),
    )
    op.create_index(
        "ix_daily_results_items_review_id",
        "daily_results_items",
        ["review_id"],
    )
    op.create_index(
        "ix_daily_results_items_trade_id",
        "daily_results_items",
        ["trade_id"],
    )
    op.create_index(
        "ix_daily_results_items_review_order",
        "daily_results_items",
        ["review_id", "display_order"],
    )


def downgrade() -> None:
    op.drop_table("daily_results_items")
    op.drop_table("daily_results_reviews")
    op.drop_column("guild_config", "results_review_channel_id")
