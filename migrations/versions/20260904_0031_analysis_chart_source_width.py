"""expand Analysis chart source for AXIS renderer name

Revision ID: 20260904_0031
Revises: 20260903_0030
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0031"
down_revision: str | None = "20260903_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "analysis_drafts",
        "chart_source",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE analysis_drafts SET chart_source = 'COSMOS' "
            "WHERE chart_source = 'AXIS_STOCK_ANALYST'"
        )
    )
    op.alter_column(
        "analysis_drafts",
        "chart_source",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
