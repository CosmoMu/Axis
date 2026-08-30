"""backfill inferred signal categories as review defaults

Revision ID: 20260830_0012
Revises: 20260830_0011
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0012"
down_revision: str | None = "20260830_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE trade_drafts
            SET selected_category = category_suggestion
            WHERE selected_category IS NULL
              AND category_suggestion IN ('SHORT_TERM', 'SWING', 'LEAPS')
            """
        )
    )


def downgrade() -> None:
    # Existing selected categories may have been changed by a Manager after upgrade;
    # a downgrade must not erase that human decision.
    pass
