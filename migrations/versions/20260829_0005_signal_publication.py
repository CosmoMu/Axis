"""add idempotent signal publication lifecycle

Revision ID: 20260829_0005
Revises: 20260829_0004
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0005"
down_revision: str | None = "20260829_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("trade_event_per_draft", "trade_events", ["draft_id"])

    op.add_column("trade_publications", sa.Column("draft_id", sa.Uuid(), nullable=True))
    op.add_column(
        "trade_publications", sa.Column("public_ref", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "trade_publications",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="PUBLISHED",
            nullable=False,
        ),
    )
    op.add_column(
        "trade_publications",
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "trade_publications", sa.Column("claim_token", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "trade_publications",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trade_publications",
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "trade_publications",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "trade_publications",
        "message_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.create_foreign_key(
        op.f("fk_trade_publications_draft_id_trade_drafts"),
        "trade_publications",
        "trade_drafts",
        ["draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_trade_publications_draft_id"),
        "trade_publications",
        ["draft_id"],
        unique=False,
    )
    op.create_unique_constraint("trade_publication_per_draft", "trade_publications", ["draft_id"])
    op.create_unique_constraint(
        "trade_public_ref_per_guild",
        "trade_publications",
        ["guild_id", "public_ref"],
    )
    op.create_check_constraint(
        op.f("ck_trade_publications_trade_publication_status"),
        "trade_publications",
        "status IN ('PENDING', 'PUBLISHED', 'FAILED')",
    )
    op.create_check_constraint(
        op.f("ck_trade_publications_trade_publication_attempt_count"),
        "trade_publications",
        "attempt_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_trade_publications_trade_publication_attempt_count"),
        "trade_publications",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_trade_publications_trade_publication_status"),
        "trade_publications",
        type_="check",
    )
    op.drop_constraint("trade_public_ref_per_guild", "trade_publications", type_="unique")
    op.drop_constraint("trade_publication_per_draft", "trade_publications", type_="unique")
    op.drop_index(op.f("ix_trade_publications_draft_id"), table_name="trade_publications")
    op.drop_constraint(
        op.f("fk_trade_publications_draft_id_trade_drafts"),
        "trade_publications",
        type_="foreignkey",
    )
    op.alter_column(
        "trade_publications",
        "message_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    for column in (
        "published_at",
        "last_error_code",
        "claimed_at",
        "claim_token",
        "attempt_count",
        "status",
        "public_ref",
        "draft_id",
    ):
        op.drop_column("trade_publications", column)
    op.drop_constraint("trade_event_per_draft", "trade_events", type_="unique")
