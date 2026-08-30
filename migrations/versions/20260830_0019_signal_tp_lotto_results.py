"""upgrade Signal TP lifecycle, LOTTO, and public result state

Revision ID: 20260830_0019
Revises: 20260830_0018
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0019"
down_revision: str | None = "20260830_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TP_LABEL_CASE = (
    "CASE tp_return_pct "
    "WHEN 20 THEN 'TP1' WHEN 50 THEN 'TP2' WHEN 100 THEN 'TP3' "
    "WHEN 150 THEN 'TP4' WHEN 200 THEN 'TP5' WHEN 300 THEN 'TP6' "
    "WHEN 400 THEN 'TP7' WHEN 500 THEN 'TP8' WHEN 750 THEN 'TP9' "
    "WHEN 1000 THEN 'TP10' ELSE public_card_type END"
)


def upgrade() -> None:
    op.add_column(
        "trade_drafts",
        sa.Column("is_lotto", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "trades",
        sa.Column("is_lotto", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.alter_column(
        "short_term_tracking",
        "milestones_hit",
        new_column_name="tp_levels_hit",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )
    op.execute(
        "UPDATE short_term_tracking AS tracking SET tp_levels_hit = COALESCE(("
        "SELECT json_agg(CASE value::integer "
        "WHEN 20 THEN 'TP1' WHEN 50 THEN 'TP2' WHEN 100 THEN 'TP3' "
        "WHEN 150 THEN 'TP4' WHEN 200 THEN 'TP5' WHEN 300 THEN 'TP6' "
        "WHEN 400 THEN 'TP7' WHEN 500 THEN 'TP8' WHEN 750 THEN 'TP9' "
        "WHEN 1000 THEN 'TP10' END ORDER BY position) "
        "FROM json_array_elements_text(tracking.tp_levels_hit) "
        "WITH ORDINALITY AS item(value, position)), '[]'::json)"
    )

    for table in (
        "short_term_tracking",
        "short_term_tracking_events",
        "short_term_daily_snapshots",
    ):
        op.alter_column(
            table,
            "reference_protection_price",
            new_column_name="tracking_protection_price",
            existing_type=sa.Numeric(18, 4),
            existing_nullable=False,
        )
    op.alter_column(
        "short_term_tracking",
        "reference_protection_return_pct",
        new_column_name="tracking_protection_return_pct",
        existing_type=sa.Numeric(12, 4),
        existing_nullable=False,
    )
    op.alter_column(
        "short_term_tracking",
        "reference_protection_reason",
        new_column_name="tracking_protection_reason",
        existing_type=sa.String(64),
        existing_nullable=False,
    )
    op.alter_column(
        "short_term_tracking_events",
        "milestone_pct",
        new_column_name="tp_return_pct",
        existing_type=sa.Integer(),
    )

    op.drop_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        type_="check",
    )
    op.execute(
        "UPDATE short_term_tracking_events "
        "SET event_type = 'FIXED_TP_HIT' "
        "WHERE event_type = 'RUNNER_MILESTONE'"
    )
    op.execute(
        "UPDATE short_term_tracking_events "
        "SET event_type = 'TRACKING_PROTECTION_MOVED' "
        "WHERE event_type = 'REFERENCE_PROTECTION_MOVED'"
    )
    op.execute(
        "UPDATE short_term_tracking_events "
        f"SET public_card_type = {TP_LABEL_CASE} "
        "WHERE event_type = 'FIXED_TP_HIT' AND tp_return_pct IS NOT NULL"
    )
    op.create_check_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT','FAST_MOMENTUM_REVERSAL',"
        "'TRACKING_PROTECTION_MOVED','TRACKING_STOPPED','OVERNIGHT_CARRY',"
        "'OVERNIGHT_GAP_STOP')",
    )

    protection_return = (
        "CASE "
        "WHEN tp_levels_hit::jsonb ? 'TP10' THEN 750 "
        "WHEN tp_levels_hit::jsonb ? 'TP9' THEN 500 "
        "WHEN tp_levels_hit::jsonb ? 'TP8' THEN 400 "
        "WHEN tp_levels_hit::jsonb ? 'TP7' THEN 300 "
        "WHEN tp_levels_hit::jsonb ? 'TP6' THEN 200 "
        "WHEN tp_levels_hit::jsonb ? 'TP5' THEN 150 "
        "WHEN tp_levels_hit::jsonb ? 'TP4' THEN 100 "
        "WHEN tp_levels_hit::jsonb ? 'TP3' THEN 50 "
        "WHEN tp_levels_hit::jsonb ? 'TP2' THEN 20 "
        "WHEN tp_levels_hit::jsonb ? 'TP1' THEN 0 ELSE -50 END"
    )
    protection_reason = (
        "CASE "
        "WHEN tp_levels_hit::jsonb ? 'TP10' THEN 'TP9_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP9' THEN 'TP8_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP8' THEN 'TP7_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP7' THEN 'TP6_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP6' THEN 'TP5_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP5' THEN 'TP4_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP4' THEN 'TP3_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP3' THEN 'TP2_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP2' THEN 'TP1_PROTECTION' "
        "WHEN tp_levels_hit::jsonb ? 'TP1' THEN 'TP1_ENTRY_PROTECTION' "
        "ELSE 'INITIAL_TRACKING_PROTECTION' END"
    )
    op.execute(
        "UPDATE short_term_tracking SET "
        f"tracking_protection_return_pct = {protection_return}, "
        f"tracking_protection_price = entry_price * (1 + ({protection_return}) / 100.0), "
        f"tracking_protection_reason = {protection_reason}, "
        "tracking_policy_version = 'ST_TRACKING_V2'"
    )
    op.execute(
        "DELETE FROM daily_summary_publications "
        "WHERE category = 'SHORT_TERM' AND status <> 'PUBLISHED'"
    )


def downgrade() -> None:
    op.drop_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        type_="check",
    )
    op.execute(
        "UPDATE short_term_tracking_events SET event_type = 'RUNNER_MILESTONE', "
        "public_card_type = 'RUNNER' "
        "WHERE event_type = 'FIXED_TP_HIT' AND tp_return_pct >= 100"
    )
    op.execute(
        "UPDATE short_term_tracking_events SET public_card_type = 'TP' "
        "WHERE event_type = 'FIXED_TP_HIT' AND tp_return_pct < 100"
    )
    op.execute(
        "UPDATE short_term_tracking_events "
        "SET event_type = 'REFERENCE_PROTECTION_MOVED' "
        "WHERE event_type = 'TRACKING_PROTECTION_MOVED'"
    )
    op.create_check_constraint(
        "short_term_event_type",
        "short_term_tracking_events",
        "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT','RUNNER_MILESTONE',"
        "'FAST_MOMENTUM_REVERSAL','REFERENCE_PROTECTION_MOVED','TRACKING_STOPPED',"
        "'OVERNIGHT_CARRY','OVERNIGHT_GAP_STOP')",
    )

    op.alter_column(
        "short_term_tracking_events",
        "tp_return_pct",
        new_column_name="milestone_pct",
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "short_term_tracking",
        "tracking_protection_reason",
        new_column_name="reference_protection_reason",
        existing_type=sa.String(64),
        existing_nullable=False,
    )
    op.alter_column(
        "short_term_tracking",
        "tracking_protection_return_pct",
        new_column_name="reference_protection_return_pct",
        existing_type=sa.Numeric(12, 4),
        existing_nullable=False,
    )
    for table in (
        "short_term_tracking",
        "short_term_tracking_events",
        "short_term_daily_snapshots",
    ):
        op.alter_column(
            table,
            "tracking_protection_price",
            new_column_name="reference_protection_price",
            existing_type=sa.Numeric(18, 4),
            existing_nullable=False,
        )

    op.execute(
        "UPDATE short_term_tracking AS tracking SET tp_levels_hit = COALESCE(("
        "SELECT json_agg(CASE value "
        "WHEN 'TP1' THEN 20 WHEN 'TP2' THEN 50 WHEN 'TP3' THEN 100 "
        "WHEN 'TP4' THEN 150 WHEN 'TP5' THEN 200 WHEN 'TP6' THEN 300 "
        "WHEN 'TP7' THEN 400 WHEN 'TP8' THEN 500 WHEN 'TP9' THEN 750 "
        "WHEN 'TP10' THEN 1000 END ORDER BY position) "
        "FROM json_array_elements_text(tracking.tp_levels_hit) "
        "WITH ORDINALITY AS item(value, position)), '[]'::json)"
    )
    op.alter_column(
        "short_term_tracking",
        "tp_levels_hit",
        new_column_name="milestones_hit",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )
    op.drop_column("trades", "is_lotto")
    op.drop_column("trade_drafts", "is_lotto")
