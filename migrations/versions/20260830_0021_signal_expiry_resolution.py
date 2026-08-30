"""add normalized signal expiry resolution metadata

Revision ID: 20260830_0021
Revises: 20260830_0020
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0021"
down_revision: str | None = "20260830_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trade_drafts", sa.Column("expiry_input", sa.String(length=32)))
    op.add_column("trade_drafts", sa.Column("expiry_precision", sa.String(length=20)))
    op.add_column(
        "trade_drafts",
        sa.Column(
            "expiry_resolution_status",
            sa.String(length=24),
            nullable=False,
            server_default="UNRESOLVED",
        ),
    )
    op.add_column("trade_drafts", sa.Column("option_contract_code", sa.String(length=64)))
    op.add_column(
        "trade_drafts",
        sa.Column(
            "contract_validation_status",
            sa.String(length=24),
            nullable=False,
            server_default="UNVALIDATED",
        ),
    )
    op.add_column(
        "trade_drafts", sa.Column("price_parse_confidence", sa.Numeric(6, 5))
    )
    op.execute(
        "UPDATE trade_drafts "
        "SET expiry_input = CAST(expiry AS VARCHAR), "
        "expiry_precision = CASE WHEN expiry IS NULL THEN NULL ELSE 'EXACT_DATE' END, "
        "expiry_resolution_status = CASE WHEN expiry IS NULL THEN 'UNRESOLVED' ELSE 'EXPLICIT' END"
    )


def downgrade() -> None:
    op.drop_column("trade_drafts", "price_parse_confidence")
    op.drop_column("trade_drafts", "contract_validation_status")
    op.drop_column("trade_drafts", "option_contract_code")
    op.drop_column("trade_drafts", "expiry_resolution_status")
    op.drop_column("trade_drafts", "expiry_precision")
    op.drop_column("trade_drafts", "expiry_input")
