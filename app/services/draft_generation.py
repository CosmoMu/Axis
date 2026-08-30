from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AuditLog,
    LlmInvocation,
    SourceAttachment,
    SourceMessage,
    TradeDraft,
)
from app.db.session import Database
from app.domain.enums import DraftStatus, SourceKind, SourceStatus
from app.integrations.openai_trade_parser import (
    LlmInvocationTrace,
    ParserAttachment,
    TradeParseError,
    TradeParseResult,
)
from app.services.attachment_storage import AttachmentStorageError, LocalAttachmentStore
from app.services.input_codes import next_input_code


class TradeParser(Protocol):
    async def parse(
        self,
        *,
        raw_text: str | None,
        attachments: list[ParserAttachment],
    ) -> TradeParseResult: ...


class DraftGenerationDisposition(StrEnum):
    CREATED = "CREATED"
    FAILED = "FAILED"
    EXISTING = "EXISTING"


@dataclass(frozen=True, slots=True)
class DraftGenerationResult:
    disposition: DraftGenerationDisposition
    draft_code: str
    channel_id: int
    discord_message_id: int


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TradeParseError("LLM_OUTPUT_VALUE_INVALID") from exc


def _date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise TradeParseError("LLM_OUTPUT_VALUE_INVALID") from exc


def _optional_enum(value: Any) -> str | None:
    if value in (None, "UNKNOWN"):
        return None
    return str(value)


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value)[:100] for value in values if str(value).strip()))


def _apply_position_ladder(payload: dict[str, Any]) -> None:
    if payload.get("category_suggestion") == "SHORT_TERM":
        payload["position_delta_eighths"] = None
        payload["position_after_eighths"] = None
        return
    if payload.get("position_delta_eighths") is not None:
        return
    if payload.get("position_after_eighths") is not None:
        return

    default: tuple[int, int] | None = None
    if payload.get("action") == "ENTRY":
        default = (1, 1)
    elif payload.get("action") == "ADD":
        default = {
            "FIRST": (1, 2),
            "SECOND": (2, 4),
            "THIRD": (2, 6),
        }.get(payload.get("add_stage"))

    if default is not None:
        payload["position_delta_eighths"], payload["position_after_eighths"] = default
        warnings = _unique_strings(payload.get("warnings"))
        if "DEFAULT_POSITION_APPLIED" not in warnings:
            warnings.append("DEFAULT_POSITION_APPLIED")
        payload["warnings"] = warnings


def _add_required_missing_fields(payload: dict[str, Any]) -> None:
    missing = _unique_strings(payload.get("missing_fields"))
    if payload.get("intent") == "UNKNOWN":
        missing.append("intent")
    if payload.get("action") == "UNKNOWN":
        missing.append("action")
    if payload.get("intent") == "NEW_TRADE":
        for field in ("ticker", "expiry", "strike"):
            if payload.get(field) is None:
                missing.append(field)
        if payload.get("option_side") == "UNKNOWN":
            missing.append("option_side")
        if all(payload.get(field) is None for field in ("entry_low", "entry_high", "action_price")):
            missing.append("entry_price")
    if (
        payload.get("category_suggestion") != "SHORT_TERM"
        and payload.get("action") in {"ENTRY", "ADD"}
        and (
            payload.get("position_delta_eighths") is None
            or payload.get("position_after_eighths") is None
        )
    ):
        missing.append("position")
    payload["missing_fields"] = list(dict.fromkeys(missing))


class DraftGenerationService:
    def __init__(
        self,
        database: Database,
        attachment_store: LocalAttachmentStore,
        parser: TradeParser,
    ) -> None:
        self.database = database
        self.attachment_store = attachment_store
        self.parser = parser

    async def process_next(self) -> DraftGenerationResult | None:
        async with self.database.session() as session:
            source_id = await session.scalar(
                select(SourceMessage.id)
                .where(
                    SourceMessage.status.in_(
                        [SourceStatus.RECEIVED.value, SourceStatus.PROCESSING.value]
                    ),
                    SourceMessage.source_kind == SourceKind.SIGNAL.value,
                    ~exists().where(TradeDraft.source_message_id == SourceMessage.id),
                )
                .order_by(SourceMessage.received_at, SourceMessage.id)
                .limit(1)
            )
        if source_id is None:
            return None
        return await self.generate(source_id)

    async def generate(self, source_message_id: uuid.UUID) -> DraftGenerationResult:
        existing = await self._existing_result(source_message_id)
        if existing is not None:
            return existing

        async with self.database.session() as session:
            source = await session.get(SourceMessage, source_message_id)
            if source is None:
                raise LookupError("source message does not exist")
            if source.status not in {
                SourceStatus.RECEIVED.value,
                SourceStatus.PROCESSING.value,
            }:
                raise ValueError("source message cannot be parsed")
            source.status = SourceStatus.PROCESSING.value
            await session.commit()
            source_snapshot = (
                source.guild_id,
                source.raw_text,
                source.submitted_by,
                source.channel_id,
                source.discord_message_id,
            )

        parse_trace: LlmInvocationTrace | None = None
        try:
            attachments = await self._load_attachments(source_message_id)
            parse_result = await self.parser.parse(
                raw_text=source_snapshot[1],
                attachments=attachments,
            )
            parse_trace = parse_result.trace
            payload = dict(parse_result.payload)
            _apply_position_ladder(payload)
            _add_required_missing_fields(payload)
            return await self._persist_success(
                source_message_id=source_message_id,
                source_snapshot=source_snapshot,
                payload=payload,
                parse_result=parse_result,
            )
        except (AttachmentStorageError, TradeParseError) as exc:
            reason_code = exc.code if isinstance(exc, TradeParseError) else "ATTACHMENT_READ_FAILED"
            failure_trace = (exc.trace or parse_trace) if isinstance(exc, TradeParseError) else None
            return await self._persist_failure(
                source_message_id=source_message_id,
                source_snapshot=source_snapshot,
                reason_code=reason_code,
                trace=failure_trace,
            )
        except Exception:
            return await self._persist_failure(
                source_message_id=source_message_id,
                source_snapshot=source_snapshot,
                reason_code="DRAFT_GENERATION_FAILED",
                trace=parse_trace,
            )

    async def _load_attachments(self, source_message_id: uuid.UUID) -> list[ParserAttachment]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(SourceAttachment)
                    .where(SourceAttachment.source_message_id == source_message_id)
                    .order_by(SourceAttachment.created_at, SourceAttachment.id)
                )
            ).all()
        attachments = []
        for row in rows:
            if row.storage_key is None or row.checksum_sha256 is None:
                raise AttachmentStorageError("attachment metadata is incomplete")
            data = await self.attachment_store.read_verified(
                row.storage_key,
                row.checksum_sha256,
            )
            attachments.append(ParserAttachment(content_type=row.content_type, data=data))
        return attachments

    async def _persist_success(
        self,
        *,
        source_message_id: uuid.UUID,
        source_snapshot: tuple[int, str | None, int, int, int],
        payload: dict[str, Any],
        parse_result: TradeParseResult,
    ) -> DraftGenerationResult:
        guild_id, _, actor_user_id, channel_id, discord_message_id = source_snapshot
        draft = self._draft_from_payload(
            source_message_id=source_message_id,
            guild_id=guild_id,
            payload=payload,
            status=DraftStatus.PENDING_REVIEW.value,
        )
        draft.parse_payload = {
            **payload,
            "_parser": {
                "provider": parse_result.trace.provider,
                "model": parse_result.trace.model,
                "workload": parse_result.trace.workload.value,
                "prompt_version": parse_result.trace.prompt_version,
                "schema_version": parse_result.trace.schema_version,
                "latency_ms": parse_result.trace.latency_ms,
                "success": parse_result.trace.success,
                "response_id": parse_result.trace.response_id,
            },
        }
        invocation = self._invocation_from_trace(
            guild_id=guild_id,
            source_message_id=source_message_id,
            trace=parse_result.trace,
        )
        draft.llm_invocation_id = invocation.id
        async with self.database.session() as session:
            source = await session.get(SourceMessage, source_message_id)
            if source is None:
                raise LookupError("source message does not exist")
            draft.draft_code = await next_input_code(session, guild_id, "SIGNAL")
            source.status = SourceStatus.PARSED.value
            session.add(invocation)
            # Flush the referenced row before inserting the draft that points to it.
            await session.flush()
            session.add(draft)
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type="TRADE_DRAFT_CREATED",
                    entity_type="trade_draft",
                    entity_id=str(draft.id),
                    before_json=None,
                    after_json={
                        "status": draft.status,
                        "draft_code": draft.draft_code,
                        "source_message_id": str(source_message_id),
                    },
                    discord_interaction_id=None,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._existing_result(source_message_id)
                if existing is None:
                    raise
                return existing
        return DraftGenerationResult(
            DraftGenerationDisposition.CREATED,
            draft.draft_code,
            channel_id,
            discord_message_id,
        )

    async def _persist_failure(
        self,
        *,
        source_message_id: uuid.UUID,
        source_snapshot: tuple[int, str | None, int, int, int],
        reason_code: str,
        trace: LlmInvocationTrace | None,
    ) -> DraftGenerationResult:
        guild_id, _, actor_user_id, channel_id, discord_message_id = source_snapshot
        payload = {
            "intent": "UNKNOWN",
            "action": "UNKNOWN",
            "add_stage": "UNKNOWN",
            "option_side": "UNKNOWN",
            "category_suggestion": "UNKNOWN",
            "confidence": 0,
            "missing_fields": ["manual_review"],
            "warnings": [reason_code],
            "summary": "LLM 解析失败，需要管理员手动检查。",
        }
        draft = self._draft_from_payload(
            source_message_id=source_message_id,
            guild_id=guild_id,
            payload=payload,
            status=DraftStatus.PARSE_FAILED.value,
        )
        invocation = (
            self._invocation_from_trace(
                guild_id=guild_id,
                source_message_id=source_message_id,
                trace=trace,
            )
            if trace is not None
            else None
        )
        if invocation is not None:
            draft.llm_invocation_id = invocation.id
        async with self.database.session() as session:
            source = await session.get(SourceMessage, source_message_id)
            if source is None:
                raise LookupError("source message does not exist")
            draft.draft_code = await next_input_code(session, guild_id, "SIGNAL")
            source.status = SourceStatus.FAILED.value
            if invocation is not None:
                session.add(invocation)
                await session.flush()
            session.add(draft)
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type="TRADE_DRAFT_PARSE_FAILED",
                    entity_type="trade_draft",
                    entity_id=str(draft.id),
                    before_json=None,
                    after_json={
                        "status": draft.status,
                        "draft_code": draft.draft_code,
                        "reason_code": reason_code,
                    },
                    discord_interaction_id=None,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._existing_result(source_message_id)
                if existing is None:
                    raise
                return existing
        return DraftGenerationResult(
            DraftGenerationDisposition.FAILED,
            draft.draft_code,
            channel_id,
            discord_message_id,
        )

    @staticmethod
    def _invocation_from_trace(
        *,
        guild_id: int,
        source_message_id: uuid.UUID,
        trace: LlmInvocationTrace,
    ) -> LlmInvocation:
        return LlmInvocation(
            id=uuid.uuid4(),
            guild_id=guild_id,
            source_message_id=source_message_id,
            provider=trace.provider,
            model=trace.model,
            workload=trace.workload.value,
            prompt_version=trace.prompt_version,
            schema_version=trace.schema_version,
            latency_ms=trace.latency_ms,
            success=trace.success,
            error_type=trace.error_type,
            provider_response_id=trace.response_id,
        )

    async def _existing_result(self, source_message_id: uuid.UUID) -> DraftGenerationResult | None:
        async with self.database.session() as session:
            row = (
                await session.execute(
                    select(TradeDraft, SourceMessage)
                    .join(SourceMessage, SourceMessage.id == TradeDraft.source_message_id)
                    .where(TradeDraft.source_message_id == source_message_id)
                )
            ).one_or_none()
        if row is None:
            return None
        draft, source = row
        return DraftGenerationResult(
            DraftGenerationDisposition.EXISTING,
            draft.draft_code,
            source.channel_id,
            source.discord_message_id,
        )

    @staticmethod
    def _draft_from_payload(
        *,
        source_message_id: uuid.UUID,
        guild_id: int,
        payload: dict[str, Any],
        status: str,
    ) -> TradeDraft:
        category_suggestion = _optional_enum(payload.get("category_suggestion"))
        return TradeDraft(
            id=uuid.uuid4(),
            guild_id=guild_id,
            draft_code="S-PENDING",
            source_message_id=source_message_id,
            matched_trade_id=None,
            mentor_id=None,
            status=status,
            intent=str(payload.get("intent", "UNKNOWN")),
            action=str(payload.get("action", "UNKNOWN")),
            action_stage=_optional_enum(payload.get("add_stage")),
            category_suggestion=category_suggestion,
            selected_category=(
                category_suggestion
                if category_suggestion in {"SHORT_TERM", "SWING", "LEAPS"}
                else "SWING"
            ),
            ticker=str(payload["ticker"]).upper() if payload.get("ticker") else None,
            expiry=_date(payload.get("expiry")),
            strike=_decimal(payload.get("strike")),
            option_side=_optional_enum(payload.get("option_side")),
            entry_low=_decimal(payload.get("entry_low")),
            entry_high=_decimal(payload.get("entry_high")),
            action_price=_decimal(payload.get("action_price")),
            avg_cost=_decimal(payload.get("avg_cost")),
            sl=_decimal(payload.get("sl")),
            tp1=_decimal(payload.get("tp1")),
            tp2=_decimal(payload.get("tp2")),
            position_delta_eighths=payload.get("position_delta_eighths"),
            position_after_eighths=payload.get("position_after_eighths"),
            current_pnl_pct=_decimal(payload.get("current_pnl_pct")),
            mentor_hint=payload.get("mentor_hint"),
            parser_confidence=_decimal(payload.get("confidence", 0)),
            parse_payload=payload,
            missing_fields=_unique_strings(payload.get("missing_fields")),
            warnings=_unique_strings(payload.get("warnings")),
            internal_notes=payload.get("summary"),
            reviewed_by=None,
            version=1,
        )
