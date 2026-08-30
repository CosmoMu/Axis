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
    AcknowledgementDocumentType,
    ActionStage,
    AnalysisDraftStatus,
    AnalysisHorizon,
    AnalysisStance,
    AnalysisType,
    DraftStatus,
    EntitlementStatus,
    EntitlementType,
    JobStatus,
    LlmWorkload,
    MembershipPlanType,
    MembershipSource,
    MembershipStatus,
    OptionSide,
    PublicationStatus,
    SourceKind,
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
    member_lounge_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    mentor_control_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    member_control_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    welcome_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    subscriptions_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    lobby_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    member_wins_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    system_alerts_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    card_testing_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    mentor_panel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    member_panel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    welcome_message_id: Mapped[int | None] = mapped_column(BigInteger)
    subscription_message_id: Mapped[int | None] = mapped_column(BigInteger)
    results_guide_message_id: Mapped[int | None] = mapped_column(BigInteger)
    lobby_guide_message_id: Mapped[int | None] = mapped_column(BigInteger)
    member_wins_guide_message_id: Mapped[int | None] = mapped_column(BigInteger)
    short_term_notice_message_id: Mapped[int | None] = mapped_column(BigInteger)


class InputCodeCounter(Base):
    __tablename__ = "input_code_counters"
    __table_args__ = (
        CheckConstraint("input_kind IN ('SIGNAL','ANALYSIS')", name="input_code_kind"),
        CheckConstraint("next_value >= 1", name="input_code_next_positive"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), primary_key=True
    )
    input_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)


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
        CheckConstraint(enum_check("source_kind", SourceKind), name="source_kind"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(
        String(16), default=SourceKind.SIGNAL.value, nullable=False
    )
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


class LlmInvocation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "llm_invocations"
    __table_args__ = (
        CheckConstraint(enum_check("workload", LlmWorkload), name="llm_invocation_workload"),
        CheckConstraint("latency_ms >= 0", name="llm_invocation_latency_nonnegative"),
        Index("ix_llm_invocations_guild_created", "guild_id", "created_at"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_messages.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    workload: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    provider_response_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class TradeDraft(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade_drafts"
    __table_args__ = (
        UniqueConstraint("guild_id", "draft_code", name="draft_code_per_guild"),
        UniqueConstraint("source_message_id", name="trade_draft_source_message"),
        UniqueConstraint("guild_id", "review_message_id", name="draft_review_message_per_guild"),
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
    llm_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_invocations.id", ondelete="SET NULL"), index=True
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
    expiry_input: Mapped[str | None] = mapped_column(String(32))
    expiry_precision: Mapped[str | None] = mapped_column(String(20))
    expiry_resolution_status: Mapped[str] = mapped_column(
        String(24), default="UNRESOLVED", nullable=False
    )
    option_contract_code: Mapped[str | None] = mapped_column(String(64))
    contract_validation_status: Mapped[str] = mapped_column(
        String(24), default="UNVALIDATED", nullable=False
    )
    price_parse_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
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
    is_lotto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    review_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    review_message_id: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Trade(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("guild_id", "public_trade_id", name="public_trade_id_per_guild"),
        UniqueConstraint("guild_id", "result_message_id", name="trade_result_message_per_guild"),
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
    mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mentors.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(12), nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    option_side: Mapped[str] = mapped_column(String(16), nullable=False)
    moomoo_option_code: Mapped[str | None] = mapped_column(String(64))
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
    is_lotto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_message_id: Mapped[int | None] = mapped_column(BigInteger)
    final_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    result_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TradeEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "trade_events"
    __table_args__ = (
        UniqueConstraint("draft_id", name="trade_event_per_draft"),
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


class ShortTermTracking(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "short_term_tracking"
    __table_args__ = (
        UniqueConstraint("trade_id", name="short_term_tracking_trade"),
        CheckConstraint(
            "tracking_state IN ('ACTIVE','OVERNIGHT_ACTIVE','STOPPED')",
            name="short_term_tracking_state",
        ),
        CheckConstraint("entry_price > 0", name="short_term_tracking_entry_positive"),
        CheckConstraint("overnight_count >= 0", name="short_term_tracking_overnight_nonnegative"),
        CheckConstraint("price_source IN ('BID','MID','LAST')", name="short_term_price_source"),
        Index("ix_short_term_tracking_guild_state", "guild_id", "tracking_state"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    option_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    current_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    highest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    highest_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    highest_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lowest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    lowest_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    lowest_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tp_levels_hit: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    momentum_tp_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    tracking_protection_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tracking_protection_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tracking_protection_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    tracking_state: Mapped[str] = mapped_column(String(24), nullable=False)
    tracking_end_reason: Mapped[str | None] = mapped_column(String(64))
    tracking_end_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tracking_end_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tracking_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    overnight_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_session_date: Mapped[date | None] = mapped_column(Date)
    closing_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    closing_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_quote_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    price_source: Mapped[str] = mapped_column(String(8), nullable=False)
    momentum_anchor_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    momentum_last_event_anchor_version: Mapped[int] = mapped_column(
        Integer, default=-1, nullable=False
    )
    momentum_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_data_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ShortTermTrackingEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "short_term_tracking_events"
    __table_args__ = (
        UniqueConstraint("tracking_id", "event_key", name="short_term_tracking_event_key"),
        UniqueConstraint("guild_id", "public_ref", name="short_term_event_public_ref"),
        UniqueConstraint("guild_id", "discord_message_id", name="short_term_event_message"),
        CheckConstraint(
            "event_type IN ('ENTRY_PUBLISHED','FIXED_TP_HIT',"
            "'FAST_MOMENTUM_REVERSAL','TRACKING_PROTECTION_MOVED','TRACKING_STOPPED',"
            "'OVERNIGHT_CARRY','OVERNIGHT_GAP_STOP')",
            name="short_term_event_type",
        ),
        Index(
            "ix_short_term_events_public_queue", "guild_id", "public_notification", "published_at"
        ),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    tracking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("short_term_tracking.id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    tp_return_pct: Mapped[int | None] = mapped_column(Integer)
    source_market_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    high_watermark_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high_watermark_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    high_watermark_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    low_watermark_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low_watermark_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tracking_protection_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    trigger_market_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    trigger_market_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    drawdown_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    tracking_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    price_source: Mapped[str] = mapped_column(String(8), nullable=False)
    public_notification: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_card_type: Mapped[str | None] = mapped_column(String(24))
    public_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    public_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    public_ref: Mapped[str | None] = mapped_column(String(32))
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class ShortTermDailySnapshot(UuidPrimaryKeyMixin, Base):
    __tablename__ = "short_term_daily_snapshots"
    __table_args__ = (
        UniqueConstraint("tracking_id", "session_date", name="short_term_daily_tracking_session"),
        Index("ix_short_term_daily_guild_session", "guild_id", "session_date"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    tracking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("short_term_tracking.id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    closing_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    closing_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    highest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    highest_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    lowest_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    lowest_return_pct: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tracking_protection_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tracking_state: Mapped[str] = mapped_column(String(24), nullable=False)
    tracking_end_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class DailyResultsPublication(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_results_publications"
    __table_args__ = (
        UniqueConstraint("guild_id", "session_date", name="daily_results_guild_session"),
        UniqueConstraint("guild_id", "message_id", name="daily_results_message"),
        CheckConstraint(enum_check("status", PublicationStatus), name="daily_results_status"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    public_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TradePublication(UuidPrimaryKeyMixin, Base):
    __tablename__ = "trade_publications"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "message_id",
            name="trade_publication_per_guild",
        ),
        UniqueConstraint("draft_id", name="trade_publication_per_draft"),
        UniqueConstraint("guild_id", "public_ref", name="trade_public_ref_per_guild"),
        CheckConstraint(enum_check("status", PublicationStatus), name="trade_publication_status"),
        CheckConstraint("attempt_count >= 0", name="trade_publication_attempt_count"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), index=True
    )
    trade_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_events.id", ondelete="SET NULL"), index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_drafts.id", ondelete="SET NULL"), index=True
    )
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    public_ref: Mapped[str | None] = mapped_column(String(20))
    custom_id: Mapped[str | None] = mapped_column(String(100))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default=PublicationStatus.PENDING.value, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claim_token: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One release-cycle import compatibility. The database and new code use TradePublication.
PublicMessage = TradePublication


class AnalysisDraft(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_drafts"
    __table_args__ = (
        UniqueConstraint("source_message_id", name="analysis_draft_per_source"),
        UniqueConstraint("guild_id", "draft_code", name="analysis_draft_code_per_guild"),
        UniqueConstraint("guild_id", "review_message_id", name="analysis_review_message_per_guild"),
        CheckConstraint(enum_check("status", AnalysisDraftStatus), name="analysis_draft_status"),
        CheckConstraint(
            "chart_source IS NULL OR chart_source IN ('SOURCE','COSMOS','AXIS_STOCK_ANALYST')",
            name="analysis_chart_source",
        ),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    draft_code: Mapped[str] = mapped_column(String(32), nullable=False)
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"), index=True
    )
    llm_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_invocations.id", ondelete="SET NULL"), index=True
    )
    mentor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mentors.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=AnalysisDraftStatus.PENDING_REVIEW.value, nullable=False
    )
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    normalized_mentor_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    market_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    conflicts_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    parser_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    review_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    review_message_id: Mapped[int | None] = mapped_column(BigInteger)
    chart_source: Mapped[str | None] = mapped_column(String(16))
    chart_source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_attachments.id", ondelete="SET NULL"), index=True
    )
    chart_storage_key: Mapped[str | None] = mapped_column(String(512))
    chart_checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    chart_content_type: Mapped[str | None] = mapped_column(String(64))
    chart_render_error: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AnalysisDraftRevision(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_draft_revisions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision", name="analysis_draft_revision_number"),
    )

    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_drafts.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_invocations.id", ondelete="SET NULL"), index=True
    )
    instruction: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class MentorAnalysis(UuidPrimaryKeyMixin, Base):
    __tablename__ = "mentor_analyses"
    __table_args__ = (
        UniqueConstraint("guild_id", "analysis_code", name="analysis_code_per_guild"),
        UniqueConstraint("draft_id", name="mentor_analysis_per_draft"),
        CheckConstraint(enum_check("analysis_type", AnalysisType), name="analysis_type"),
        CheckConstraint(enum_check("stance", AnalysisStance), name="analysis_stance"),
        CheckConstraint(enum_check("time_horizon", AnalysisHorizon), name="analysis_horizon"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    analysis_code: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_drafts.id", ondelete="RESTRICT"), index=True
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="RESTRICT"), index=True
    )
    mentor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentors.id", ondelete="RESTRICT"), index=True
    )
    analysis_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stance: Mapped[str] = mapped_column(String(16), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str | None] = mapped_column(String(160))
    summary: Mapped[str | None] = mapped_column(Text)
    core_thesis: Mapped[str | None] = mapped_column(Text)
    why_now_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    invalidation: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(String(120))
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_source_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized_mentor_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stock_analyst_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    final_fused_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    conflict_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    publication_status: Mapped[str | None] = mapped_column(String(16))
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    llm_workload: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class AnalysisSymbol(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_symbols"
    __table_args__ = (
        UniqueConstraint("analysis_id", "symbol", "symbol_kind", name="analysis_symbol_unique"),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    symbol_kind: Mapped[str] = mapped_column(String(16), nullable=False)


class AnalysisKeyLevel(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_key_levels"
    __table_args__ = (
        CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name="analysis_key_level_source",
        ),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str | None] = mapped_column(String(12))
    level_type: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    strength: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    note: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(32), default="MENTOR_INPUT", nullable=False)


class AnalysisPoint(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_points"
    __table_args__ = (
        UniqueConstraint("analysis_id", "point_type", "position", name="analysis_point_position"),
        CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name="analysis_point_source",
        ),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    point_type: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="MENTOR_INPUT", nullable=False)


class AnalysisIndicator(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_indicators"
    __table_args__ = (
        UniqueConstraint("analysis_id", "position", name="analysis_indicator_position"),
        CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name="analysis_indicator_source",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(80), nullable=False)
    indicator_value: Mapped[str | None] = mapped_column(String(120))
    indicator_interpretation: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisScenario(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_scenarios"
    __table_args__ = (
        UniqueConstraint("analysis_id", "position", name="analysis_scenario_position"),
        CheckConstraint(
            "source IN ('MENTOR_INPUT','STOCK_ANALYST')",
            name="analysis_scenario_source",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    model_weight_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(500))
    targets_json: Mapped[list[float]] = mapped_column(JSON, default=list, nullable=False)
    invalidation: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    rationale: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class AnalysisPredictionPoint(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_prediction_points"
    __table_args__ = (
        UniqueConstraint("analysis_id", "sequence", name="analysis_prediction_point_sequence"),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    point_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))


class AnalysisPublication(UuidPrimaryKeyMixin, Base):
    __tablename__ = "analysis_publications"
    __table_args__ = (
        UniqueConstraint("analysis_id", name="analysis_publication_per_analysis"),
        UniqueConstraint("guild_id", "message_id", name="analysis_publication_message"),
        UniqueConstraint("guild_id", "public_ref", name="analysis_public_ref"),
        CheckConstraint(
            enum_check("status", PublicationStatus), name="analysis_publication_status"
        ),
    )
    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mentor_analyses.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    public_ref: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketQuoteSnapshot(UuidPrimaryKeyMixin, Base):
    __tablename__ = "market_quote_snapshots"
    __table_args__ = (
        UniqueConstraint("trade_id", "session_date", name="market_quote_trade_session"),
        CheckConstraint("last_price > 0", name="market_quote_price_positive"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    last_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    market_state: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class DailySummaryPublication(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_summary_publications"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "category",
            "session_date",
            name="daily_summary_guild_category_session",
        ),
        UniqueConstraint("guild_id", "message_id", name="daily_summary_message"),
        UniqueConstraint("guild_id", "public_ref", name="daily_summary_public_ref"),
        CheckConstraint(enum_check("category", TradeCategory), name="daily_summary_category"),
        CheckConstraint(enum_check("status", PublicationStatus), name="daily_summary_status"),
        CheckConstraint("attempt_count >= 0", name="daily_summary_attempt_nonnegative"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    public_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id", name="membership_user_per_guild"),
        UniqueConstraint(
            "provider",
            "provider_subscription_id",
            name="membership_provider_subscription",
        ),
        CheckConstraint(enum_check("status", MembershipStatus), name="membership_status"),
        CheckConstraint(enum_check("source", MembershipSource), name="membership_source"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column("discord_user_id", BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=MembershipStatus.ACTIVE.value, nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_customer_id: Mapped[str | None] = mapped_column(String(255))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255))
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


class MembershipPrice(UuidPrimaryKeyMixin, Base):
    __tablename__ = "membership_prices"
    __table_args__ = (
        UniqueConstraint("plan_type", "pricing_version", name="membership_price_version"),
        UniqueConstraint("stripe_price_id", name="membership_stripe_price"),
        CheckConstraint(enum_check("plan_type", MembershipPlanType), name="membership_price_plan"),
        CheckConstraint("unit_amount >= 0", name="membership_price_amount_nonnegative"),
    )

    plan_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    pricing_version: Mapped[str] = mapped_column(String(40), nullable=False)
    stripe_product_id: Mapped[str | None] = mapped_column(String(255))
    stripe_price_id: Mapped[str | None] = mapped_column(String(255))
    unit_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    billing_interval: Mapped[str | None] = mapped_column(String(16))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MembershipAcknowledgement(UuidPrimaryKeyMixin, Base):
    __tablename__ = "membership_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "discord_user_id",
            "document_type",
            "document_version",
            name="membership_acknowledgement_once",
        ),
        CheckConstraint(
            enum_check("document_type", AcknowledgementDocumentType),
            name="membership_acknowledgement_document_type",
        ),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(24), nullable=False)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discord_interaction_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class MembershipEntitlement(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "membership_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subscription_id", name="entitlement_provider_subscription"
        ),
        UniqueConstraint(
            "provider", "provider_checkout_session_id", name="entitlement_provider_checkout"
        ),
        CheckConstraint(enum_check("entitlement_type", EntitlementType), name="entitlement_type"),
        CheckConstraint(enum_check("status", EntitlementStatus), name="entitlement_status"),
        CheckConstraint(
            "unit_amount_at_signup IS NULL OR unit_amount_at_signup >= 0",
            name="entitlement_amount_nonnegative",
        ),
        Index("ix_entitlements_user_status", "guild_id", "discord_user_id", "status"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    entitlement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_trading_day: Mapped[date | None] = mapped_column(Date)
    last_trading_day: Mapped[date | None] = mapped_column(Date)
    membership_price_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("membership_prices.id", ondelete="RESTRICT"), index=True
    )
    pricing_version: Mapped[str | None] = mapped_column(String(40))
    stripe_price_id: Mapped[str | None] = mapped_column(String(255))
    unit_amount_at_signup: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_checkout_session_id: Mapped[str | None] = mapped_column(String(255), index=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_entitlement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("membership_entitlements.id", ondelete="SET NULL"), index=True
    )
    granted_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    extension_type: Mapped[str | None] = mapped_column(String(24))
    extension_amount: Mapped[int | None] = mapped_column(Integer)
    old_effective_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_effective_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MembershipTrial(UuidPrimaryKeyMixin, Base):
    __tablename__ = "membership_trials"
    __table_args__ = (
        UniqueConstraint("discord_user_id", "trial_type", name="membership_trial_lifetime_once"),
        CheckConstraint("trading_days_granted > 0", name="membership_trial_days_positive"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    trial_type: Mapped[str] = mapped_column(String(24), nullable=False)
    trading_days_granted: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    last_trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    entitlement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("membership_entitlements.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class PaymentEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="payment_event_provider_id"),
        Index("ix_payment_events_user_created", "discord_user_id", "created_at"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    discord_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("membership_entitlements.id", ondelete="SET NULL"), index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
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


class MembershipSession(Base):
    __tablename__ = "membership_sessions"
    __table_args__ = (
        Index("ix_membership_sessions_user_created", "discord_user_id", "created_at"),
    )

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    membership_type: Mapped[str | None] = mapped_column(String(24))
    pricing_version: Mapped[str | None] = mapped_column(String(40))
    membership_price_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("membership_prices.id", ondelete="RESTRICT"), index=True
    )
    provider_checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentWebhookEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="payment_provider_event"),
        Index("ix_payment_webhooks_received", "received_at"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("membership_sessions.session_id", ondelete="SET NULL"), index=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemAlert(UuidPrimaryKeyMixin, Base):
    __tablename__ = "system_alerts"
    __table_args__ = (
        UniqueConstraint("guild_id", "fingerprint", name="system_alert_fingerprint"),
        CheckConstraint(
            "severity IN ('WARNING','ERROR')",
            name="system_alert_severity",
        ),
        CheckConstraint("occurrence_count >= 1", name="system_alert_occurrence_positive"),
        Index("ix_system_alerts_active", "guild_id", "resolved_at", "last_seen"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guild_config.guild_id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    affected: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
