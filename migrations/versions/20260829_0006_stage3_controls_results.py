"""add official result publication fields

Revision ID: 20260829_0006
Revises: 20260829_0005
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0006"
down_revision: str | None = "20260829_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("result_message_id", sa.BigInteger(), nullable=True))
    op.add_column("trades", sa.Column("final_return_pct", sa.Numeric(12, 4), nullable=True))
    op.add_column(
        "trades",
        sa.Column("result_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "trade_result_message_per_guild",
        "trades",
        ["guild_id", "result_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint("trade_result_message_per_guild", "trades", type_="unique")
    op.drop_column("trades", "result_published_at")
    op.drop_column("trades", "final_return_pct")
    op.drop_column("trades", "result_message_id")
