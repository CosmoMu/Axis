"""make trade draft generation idempotent per source message

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0002"
down_revision: str | None = "20260829_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "trade_draft_source_message",
        "trade_drafts",
        ["source_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "trade_draft_source_message",
        "trade_drafts",
        type_="unique",
    )
