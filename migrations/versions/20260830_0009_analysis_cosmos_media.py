"""add Cosmos context and approved media to Analysis drafts

Revision ID: 20260830_0009
Revises: 20260829_0008
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0009"
down_revision: str | None = "20260829_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_drafts",
        sa.Column(
            "cosmos_context_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column("analysis_drafts", sa.Column("chart_source", sa.String(length=16), nullable=True))
    op.add_column(
        "analysis_drafts",
        sa.Column("chart_source_attachment_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "analysis_drafts",
        sa.Column("chart_storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "analysis_drafts",
        sa.Column("chart_checksum_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "analysis_drafts",
        sa.Column("chart_content_type", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        "chart_source IS NULL OR chart_source IN ('SOURCE','COSMOS')",
    )
    op.create_foreign_key(
        op.f("fk_analysis_drafts_chart_source_attachment_id_source_attachments"),
        "analysis_drafts",
        "source_attachments",
        ["chart_source_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_analysis_drafts_chart_source_attachment_id"),
        "analysis_drafts",
        ["chart_source_attachment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_analysis_drafts_chart_source_attachment_id"),
        table_name="analysis_drafts",
    )
    op.drop_constraint(
        op.f("fk_analysis_drafts_chart_source_attachment_id_source_attachments"),
        "analysis_drafts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_analysis_drafts_analysis_chart_source"),
        "analysis_drafts",
        type_="check",
    )
    for column in (
        "chart_content_type",
        "chart_checksum_sha256",
        "chart_storage_key",
        "chart_source_attachment_id",
        "chart_source",
        "cosmos_context_json",
    ):
        op.drop_column("analysis_drafts", column)
