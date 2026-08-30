"""remove legacy Mentor links from Short-Term records

Revision ID: 20260830_0020
Revises: 20260830_0019
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0020"
down_revision: str | None = "20260830_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE trades SET mentor_id = NULL WHERE category = 'SHORT_TERM'")
    op.execute(
        "UPDATE trade_drafts SET mentor_id = NULL, matched_trade_id = NULL "
        "WHERE COALESCE(selected_category, category_suggestion) = 'SHORT_TERM'"
    )


def downgrade() -> None:
    # Removed legacy links cannot be reconstructed safely. Short-Term remains no-Mentor.
    pass
