"""rename embedded market intelligence and add training provenance

Revision ID: 20260830_0010
Revises: 20260830_0009
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0010"
down_revision: str | None = "20260830_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "analysis_drafts",
        "cosmos_context_json",
        new_column_name="market_context_json",
    )
    op.drop_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        "chart_source IS NULL OR chart_source IN ('SOURCE','COSMOS','AXIS_STOCK_ANALYST')",
    )
    op.add_column(
        "mentor_analyses",
        sa.Column(
            "why_now_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    for table in ("analysis_key_levels", "analysis_points"):
        op.add_column(
            table,
            sa.Column(
                "source",
                sa.String(length=32),
                server_default=sa.text("'INPUT'"),
                nullable=False,
            ),
        )
    op.create_check_constraint(
        op.f("ck_analysis_key_levels_analysis_key_level_source"),
        "analysis_key_levels",
        "source IN ('INPUT','AXIS_STOCK_ANALYST')",
    )
    op.create_check_constraint(
        op.f("ck_analysis_points_analysis_point_source"),
        "analysis_points",
        "source IN ('INPUT','AXIS_STOCK_ANALYST')",
    )


def downgrade() -> None:
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
    op.drop_column("analysis_points", "source")
    op.drop_column("analysis_key_levels", "source")
    op.drop_column("mentor_analyses", "why_now_json")
    op.drop_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        "chart_source IS NULL OR chart_source IN ('SOURCE','COSMOS')",
    )
    op.alter_column(
        "analysis_drafts",
        "market_context_json",
        new_column_name="cosmos_context_json",
    )
