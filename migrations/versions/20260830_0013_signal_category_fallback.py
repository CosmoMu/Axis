"""default uncategorized signal drafts to swing

Revision ID: 20260830_0013
Revises: 20260830_0012
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0013"
down_revision: str | None = "20260830_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE trade_drafts
            SET selected_category = 'SWING'
            WHERE selected_category IS NULL
            """
        )
    )


def downgrade() -> None:
    # Managers may have changed a fallback after upgrade. Preserve that decision.
    pass
