"""add Discord review message identity to trade drafts

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0003"
down_revision: str | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trade_drafts", sa.Column("review_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("trade_drafts", sa.Column("review_message_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(
        "draft_review_message_per_guild",
        "trade_drafts",
        ["guild_id", "review_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "draft_review_message_per_guild",
        "trade_drafts",
        type_="unique",
    )
    op.drop_column("trade_drafts", "review_message_id")
    op.drop_column("trade_drafts", "review_channel_id")
