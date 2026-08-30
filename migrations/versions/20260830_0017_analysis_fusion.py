"""add mentor-first Analysis fusion provenance and scenarios

Revision ID: 20260830_0017
Revises: 20260830_0016
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0017"
down_revision: str | None = "20260830_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_drafts",
        sa.Column(
            "normalized_mentor_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_drafts",
        sa.Column(
            "conflicts_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_drafts", sa.Column("chart_render_error", sa.String(length=64), nullable=True)
    )
    for name, default in (
        ("raw_source_json", "'{}'"),
        ("normalized_mentor_json", "'{}'"),
        ("stock_analyst_snapshot", "'{}'"),
        ("final_fused_json", "'{}'"),
    ):
        op.add_column(
            "mentor_analyses",
            sa.Column(name, sa.JSON(), server_default=sa.text(default), nullable=False),
        )
    op.add_column(
        "mentor_analyses",
        sa.Column(
            "conflict_detected",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.drop_constraint(
        op.f("ck_analysis_key_levels_analysis_key_level_source"),
        "analysis_key_levels",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_analysis_points_analysis_point_source"),
        "analysis_points",
        type_="check",
    )
    op.execute("UPDATE analysis_key_levels SET source = 'MENTOR_INPUT' WHERE source = 'INPUT'")
    op.execute(
        "UPDATE analysis_key_levels SET source = 'STOCK_ANALYST' "
        "WHERE source = 'AXIS_STOCK_ANALYST'"
    )
    op.execute("UPDATE analysis_points SET source = 'MENTOR_INPUT' WHERE source = 'INPUT'")
    op.execute(
        "UPDATE analysis_points SET source = 'STOCK_ANALYST' "
        "WHERE source = 'AXIS_STOCK_ANALYST'"
    )
    op.create_check_constraint(
        op.f("ck_analysis_key_levels_analysis_key_level_source"),
        "analysis_key_levels",
        "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
    )
    op.create_check_constraint(
        op.f("ck_analysis_points_analysis_point_source"),
        "analysis_points",
        "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
    )
    op.add_column("analysis_key_levels", sa.Column("price_high", sa.Numeric(18, 4)))
    op.add_column("analysis_key_levels", sa.Column("strength", sa.Numeric(6, 2)))
    op.add_column("analysis_key_levels", sa.Column("description", sa.String(length=500)))
    op.execute("UPDATE analysis_key_levels SET description = note WHERE note IS NOT NULL")

    op.create_table(
        "analysis_indicators",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("indicator_name", sa.String(length=80), nullable=False),
        sa.Column("indicator_value", sa.String(length=120)),
        sa.Column("indicator_interpretation", sa.String(length=500)),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name=op.f("ck_analysis_indicators_analysis_indicator_source"),
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "position", name="analysis_indicator_position"),
    )
    op.create_index("ix_analysis_indicators_analysis_id", "analysis_indicators", ["analysis_id"])

    op.create_table(
        "analysis_scenarios",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("model_weight_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("trigger", sa.String(length=500)),
        sa.Column("targets_json", sa.JSON(), nullable=False),
        sa.Column("invalidation", sa.Numeric(18, 4)),
        sa.Column("rationale", sa.String(length=1000)),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name=op.f("ck_analysis_scenarios_analysis_scenario_source"),
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "position", name="analysis_scenario_position"),
    )
    op.create_index("ix_analysis_scenarios_analysis_id", "analysis_scenarios", ["analysis_id"])

    op.create_table(
        "analysis_prediction_points",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.SmallInteger(), nullable=False),
        sa.Column("point_type", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("label", sa.String(length=120)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "sequence", name="analysis_prediction_point_sequence"
        ),
    )
    op.create_index(
        "ix_analysis_prediction_points_analysis_id",
        "analysis_prediction_points",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_table("analysis_prediction_points")
    op.drop_table("analysis_scenarios")
    op.drop_table("analysis_indicators")
    for column in ("description", "strength", "price_high"):
        op.drop_column("analysis_key_levels", column)
    op.drop_constraint(
        op.f("ck_analysis_points_analysis_point_source"),
        "analysis_points",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_analysis_key_levels_analysis_key_level_source"),
        "analysis_key_levels",
        type_="check",
    )
    op.execute("UPDATE analysis_points SET source = 'INPUT' WHERE source = 'MENTOR_INPUT'")
    op.execute(
        "UPDATE analysis_points SET source = 'AXIS_STOCK_ANALYST' "
        "WHERE source = 'STOCK_ANALYST'"
    )
    op.execute("UPDATE analysis_key_levels SET source = 'INPUT' WHERE source = 'MENTOR_INPUT'")
    op.execute(
        "UPDATE analysis_key_levels SET source = 'AXIS_STOCK_ANALYST' "
        "WHERE source = 'STOCK_ANALYST'"
    )
    op.create_check_constraint(
        op.f("ck_analysis_points_analysis_point_source"),
        "analysis_points",
        "source IN ('INPUT','AXIS_STOCK_ANALYST')",
    )
    op.create_check_constraint(
        op.f("ck_analysis_key_levels_analysis_key_level_source"),
        "analysis_key_levels",
        "source IN ('INPUT','AXIS_STOCK_ANALYST')",
    )
    for column in (
        "conflict_detected",
        "final_fused_json",
        "stock_analyst_snapshot",
        "normalized_mentor_json",
        "raw_source_json",
    ):
        op.drop_column("mentor_analyses", column)
    for column in ("chart_render_error", "conflicts_json", "normalized_mentor_json"):
        op.drop_column("analysis_drafts", column)
