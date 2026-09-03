"""persist idempotent approval welcome messages

Revision ID: 20260902_0028
Revises: 20260901_0027
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0028"
down_revision: str | None = "20260901_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "access_applications",
        sa.Column("lobby_welcome_message_id", sa.BigInteger()),
    )
    op.add_column(
        "access_applications",
        sa.Column("member_lounge_welcome_message_id", sa.BigInteger()),
    )


def downgrade() -> None:
    op.drop_column("access_applications", "member_lounge_welcome_message_id")
    op.drop_column("access_applications", "lobby_welcome_message_id")
