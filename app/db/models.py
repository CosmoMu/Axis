from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import (
    ActionStage,
    DraftStatus,
    JobStatus,
    MembershipSource,
    MembershipStatus,
    OptionSide,
    SourceStatus,
    TradeAction,
    TradeCategory,
    TradeState,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def enum_check(column: str, values: type) -> str:
    allowed = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({allowed})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class UuidPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class GuildConfig(TimestampMixin, Base):
    __tablename__ = "guild_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Toronto", nullable=False)
    subscription_url: Mapped[str | None] = mapped_column(Text)
    weekly_results_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lab_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manager_role_id: Mapped[int | None] = mapped_column(BigInteger)
    member_role_id: Mapped[int | None] = mapped_column(BigInteger)
    results_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    short_term_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    swing_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    leaps_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    mentor_control_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    member_control_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    mentor_panel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    member_panel_message_id: Mapped[int | None] = mapped_column(BigInteger)


class Mentor(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mentors"
    __table_args__ = (
        UniqueConstraint("guild_id", "name", name="mentor_name_per_guild"),
        UniqueConstraint("guild_id", "short_code", name="mentor_code_per_guild"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_code: Mapped[str] = mapped_column(String(24), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MentorAlias(UuidPrimaryKeyMixin, Base):
    __tablename__ = "mentor_aliases"
    __table_args__ = (
        UniqueConstraint("guild_id", "normalized_alias", name="mentor_alias_per_guild"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentors.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class SourceMessage(UuidPrimaryKeyMixin, Base):
    __tablename__ = "source_messages"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_message_id", name="source_message_per_guild"),
        CheckConstraint(enum_check("status", SourceStatus), name="source_status"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(24), default=SourceStatus.RECEIVED.value, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class SourceAttachment(UuidPrimaryKeyMixin, Base):
    __tablename__ = "source_attachments"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="attachment_size_nonnegative"),)

    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="CASCADE"), index=True
    )
    discord_attachment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class TradeDraft(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade_drafts"
    __table_args__ = (
        UniqueConstraint("guild_id", "draft_code", name="draft_code_per_guild"),
        CheckConstraint(enum_check("status", DraftStatus), name="draft_status"),
        CheckConstraint("position_delta_eighths BETWEEN -8 AND 8", name="draft_position_delta"),
        CheckConstraint("position_after_eighths BETWEEN 0 AND 8", name="draft_position_after"),
        CheckConstraint("parser_confidence BETWEEN 0 AND 1", name="parser_confidence"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    draft_code: Mapped[str] = mapped_column(String(32), nullable=False)
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"), index=True
    )
    matched_trade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), index=True
    )
    mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mentors.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=DraftStatus.PENDING_REVIEW.value, nullable=False
    )
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    action_stage: Mapped[str | None] = mapped_column(String(16))
    category_suggestion: Mapped[str | None] = mapped_column(String(32))
    selected_category: Mapped[str | None] = mapped_column(String(32))
    ticker: Mapped[str | None] = mapped_column(String(12))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    option_side: Mapped[str | None] = mapped_column(String(16))
    entry_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    action_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp1: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp2: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    position_delta_eighths: Mapped[int | None] = mapped_column(SmallInteger)
    position_after_eighths: Mapped[int | None] = mapped_column(SmallInteger)
    current_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    mentor_hint: Mapped[str | None] = mapped_column(String(100))
    parser_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    parse_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Trade(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("guild_id", "public_trade_id", name="public_trade_id_per_guild"),
        CheckConstraint(enum_check("category", TradeCategory), name="trade_category"),
        CheckConstraint(enum_check("option_side", OptionSide), name="trade_option_side"),
        CheckConstraint(enum_check("state", TradeState), name="trade_state"),
        CheckConstraint("position_eighths BETWEEN 0 AND 8", name="trade_position"),
        CheckConstraint("max_position_eighths BETWEEN 0 AND 8", name="trade_max_position"),
        CheckConstraint(
            "entry_low IS NULL OR entry_high IS NULL OR entry_low <= entry_high",
            name="trade_entry_range",
        ),
        Index("ix_trades_guild_state_category", "guild_id", "state", "category"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    public_trade_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentors.id", ondelete="RESTRICT"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12), nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    option_side: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default=TradeState.DRAFT.value, nullable=False)
    last_public_action: Mapped[str | None] = mapped_column(String(32))
    position_eighths: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    max_position_eighths: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    entry_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp1: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp2: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TradeEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "trade_events"
    __table_args__ = (
        CheckConstraint(enum_check("action", TradeAction), name="trade_event_action"),
        CheckConstraint(enum_check("action_stage", ActionStage), name="trade_event_stage"),
        CheckConstraint("position_delta_eighths BETWEEN -8 AND 8", name="event_position_delta"),
        CheckConstraint("position_after_eighths BETWEEN 0 AND 8", name="event_position_after"),
        Index("ix_trade_events_trade_created", "trade_id", "created_at"),
    )

    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    action_stage: Mapped[str] = mapped_column(
        String(16), default=ActionStage.NONE.value, nullable=False
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    position_delta_eighths: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position_after_eighths: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    avg_cost_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    sl_before: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sl_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp1_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tp2_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_messages.id", ondelete="SET NULL"), index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_drafts.id", ondelete="SET NULL"), index=True
    )
    approved_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class PublicMessage(UuidPrimaryKeyMixin, Base):
    __tablename__ = "public_messages"
    __table_args__ = (UniqueConstraint("guild_id", "message_id", name="public_message_per_guild"),)

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), index=True
    )
    trade_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_events.id", ondelete="SET NULL"), index=True
    )
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    custom_id: Mapped[str | None] = mapped_column(String(100))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="membership_user_per_guild"),
        CheckConstraint(enum_check("status", MembershipStatus), name="membership_status"),
        CheckConstraint(enum_check("source", MembershipSource), name="membership_source"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=MembershipStatus.ACTIVE.value, nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    removal_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MembershipEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "membership_events"
    __table_args__ = (
        Index("ix_membership_events_membership_created", "membership_id", "created_at"),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class Subscription(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "external_subscription_id", name="provider_subscription"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_customer_id: Mapped[str | None] = mapped_column(String(255))
    external_subscription_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(UuidPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_guild_created", "guild_id", "created_at"),)

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    discord_interaction_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class ScheduledJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="scheduled_job_dedupe_key"),
        CheckConstraint(enum_check("status", JobStatus), name="scheduled_job_status"),
        CheckConstraint("attempts >= 0", name="scheduled_job_attempts"),
        CheckConstraint("max_attempts > 0", name="scheduled_job_max_attempts"),
        Index("ix_scheduled_jobs_due", "status", "run_at"),
    )

    guild_id: Mapped[int | None] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING.value, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
