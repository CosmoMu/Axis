"""add the independent Short-Term earnings flag

Revision ID: 20260910_0032
Revises: 20260904_0031
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0032"
down_revision: str | None = "20260904_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trade_drafts",
        sa.Column("is_er", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "trades",
        sa.Column("is_er", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("trades", "is_er")
    op.drop_column("trade_drafts", "is_er")
