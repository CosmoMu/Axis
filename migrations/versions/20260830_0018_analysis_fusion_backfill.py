"""backfill Analysis fusion snapshots for pre-0017 rows

Revision ID: 20260830_0018
Revises: 20260830_0017
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0018"
down_revision: str | None = "20260830_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE analysis_drafts "
        "SET normalized_mentor_json = normalized_json "
        "WHERE normalized_mentor_json::text = '{}'"
    )
    op.execute(
        "UPDATE mentor_analyses AS analysis "
        "SET normalized_mentor_json = analysis.normalized_json, "
        "final_fused_json = analysis.normalized_json, "
        "stock_analyst_snapshot = draft.market_context_json "
        "FROM analysis_drafts AS draft "
        "WHERE draft.id = analysis.draft_id "
        "AND analysis.normalized_mentor_json::text = '{}'"
    )
    op.execute(
        "UPDATE mentor_analyses AS analysis "
        "SET raw_source_json = json_build_object("
        "'text', source.raw_text, "
        "'source_message_id', source.id::text, "
        "'attachments', '[]'::json"
        ") "
        "FROM source_messages AS source "
        "WHERE source.id = analysis.source_message_id "
        "AND analysis.raw_source_json::text = '{}'"
    )


def downgrade() -> None:
    # Snapshot backfill is intentionally preserved; deleting historical provenance is unsafe.
    pass
