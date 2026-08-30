"""add isolated analysis pipeline domain

Revision ID: 20260829_0007
Revises: 20260829_0006
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0007"
down_revision: str | None = "20260829_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "guild_config", sa.Column("member_lounge_channel_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "source_messages",
        sa.Column("source_kind", sa.String(length=16), server_default="SIGNAL", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_source_messages_source_kind"),
        "source_messages",
        "source_kind IN ('SIGNAL', 'ANALYSIS')",
    )

    op.create_table(
        "analysis_drafts",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_code", sa.String(32), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.Column("llm_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("mentor_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("parser_confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("review_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("review_message_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING_REVIEW','PARSE_FAILED','ARCHIVED','PUBLISHED',"
            "'PUBLISH_FAILED','DELETED')",
            name=op.f("ck_analysis_drafts_analysis_draft_status"),
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["source_messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["llm_invocation_id"], ["llm_invocations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mentor_id"], ["mentors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_message_id", name="analysis_draft_per_source"),
        sa.UniqueConstraint("guild_id", "draft_code", name="analysis_draft_code_per_guild"),
        sa.UniqueConstraint(
            "guild_id", "review_message_id", name="analysis_review_message_per_guild"
        ),
    )
    for column in ("guild_id", "source_message_id", "llm_invocation_id", "mentor_id"):
        op.create_index(f"ix_analysis_drafts_{column}", "analysis_drafts", [column])

    op.create_table(
        "analysis_draft_revisions",
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("llm_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("instruction", sa.String(64), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["analysis_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["llm_invocation_id"], ["llm_invocations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "revision", name="analysis_draft_revision_number"),
    )
    op.create_index(
        "ix_analysis_draft_revisions_draft_id", "analysis_draft_revisions", ["draft_id"]
    )
    op.create_index(
        "ix_analysis_draft_revisions_llm_invocation_id",
        "analysis_draft_revisions",
        ["llm_invocation_id"],
    )

    op.create_table(
        "mentor_analyses",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_code", sa.String(32), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.Column("mentor_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_type", sa.String(16), nullable=False),
        sa.Column("stance", sa.String(16), nullable=False),
        sa.Column("time_horizon", sa.String(16), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("core_thesis", sa.Text(), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("sector", sa.String(120), nullable=True),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("public_snapshot", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publication_status", sa.String(16), nullable=True),
        sa.Column("market_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("llm_workload", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "analysis_type IN ('MARKET','TICKER','SECTOR','MACRO')",
            name=op.f("ck_mentor_analyses_analysis_type"),
        ),
        sa.CheckConstraint(
            "stance IN ('BULLISH','BEARISH','NEUTRAL','WATCH')",
            name=op.f("ck_mentor_analyses_analysis_stance"),
        ),
        sa.CheckConstraint(
            "time_horizon IN ('INTRADAY','SHORT_TERM','SWING','LONG_TERM','UNSPECIFIED')",
            name=op.f("ck_mentor_analyses_analysis_horizon"),
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["analysis_drafts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_message_id"], ["source_messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mentor_id"], ["mentors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "analysis_code", name="analysis_code_per_guild"),
        sa.UniqueConstraint("draft_id", name="mentor_analysis_per_draft"),
    )
    for column in ("guild_id", "draft_id", "source_message_id", "mentor_id"):
        op.create_index(f"ix_mentor_analyses_{column}", "mentor_analyses", [column])

    op.create_table(
        "analysis_symbols",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("symbol_kind", sa.String(16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "symbol", "symbol_kind", name="analysis_symbol_unique"),
    )
    op.create_index("ix_analysis_symbols_analysis_id", "analysis_symbols", ["analysis_id"])
    op.create_table(
        "analysis_key_levels",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=True),
        sa.Column("level_type", sa.String(16), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_key_levels_analysis_id", "analysis_key_levels", ["analysis_id"])
    op.create_table(
        "analysis_points",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("point_type", sa.String(32), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "point_type", "position", name="analysis_point_position"
        ),
    )
    op.create_index("ix_analysis_points_analysis_id", "analysis_points", ["analysis_id"])
    op.create_table(
        "analysis_publications",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("public_ref", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','PUBLISHED','FAILED')",
            name=op.f("ck_analysis_publications_analysis_publication_status"),
        ),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_config.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["mentor_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="analysis_publication_per_analysis"),
        sa.UniqueConstraint("guild_id", "message_id", name="analysis_publication_message"),
        sa.UniqueConstraint("guild_id", "public_ref", name="analysis_public_ref"),
    )
    op.create_index("ix_analysis_publications_guild_id", "analysis_publications", ["guild_id"])
    op.create_index(
        "ix_analysis_publications_analysis_id", "analysis_publications", ["analysis_id"]
    )


def downgrade() -> None:
    for table in (
        "analysis_publications",
        "analysis_points",
        "analysis_key_levels",
        "analysis_symbols",
        "mentor_analyses",
        "analysis_draft_revisions",
        "analysis_drafts",
    ):
        op.drop_table(table)
    op.drop_constraint(op.f("ck_source_messages_source_kind"), "source_messages", type_="check")
    op.drop_column("source_messages", "source_kind")
    op.drop_column("guild_config", "member_lounge_channel_id")
