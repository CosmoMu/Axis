from __future__ import annotations

import re
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
    Trade,
    TradeDraft,
)
from app.db.session import Database
from app.domain.enums import DraftStatus, SourceKind, SourceStatus
from app.integrations.massive_market_data import MarketDataProvider, MarketPriceRequest
from app.integrations.openai_trade_parser import (
    LlmInvocationTrace,
    ParserAttachment,
    TradeParseError,
    TradeParseResult,
)
from app.services.attachment_storage import AttachmentStorageError, LocalAttachmentStore
from app.services.input_codes import next_input_code
from app.services.option_contracts import (
    ContractValidationStatus,
    ExpiryPrecision,
    ExpiryRequest,
    ExpiryResolution,
    ExpiryResolutionStatus,
    OptionContractResolver,
    extract_expiry_input,
    parse_expiry_input,
    parse_fast_signal,
    parse_swing_close,
)
from app.services.swing_tracking import SIMPLE_TRACKED_SWING


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


def _prepare_signal_payload(payload: dict[str, Any], raw_text: str | None) -> None:
    close = parse_swing_close(raw_text)
    if close is not None:
        payload.update(
            {
                "intent": "UPDATE_TRADE",
                "action": "CLOSE",
                "add_stage": None,
                "category_suggestion": "SWING",
                "selected_category": "SWING",
                "_swing_mode": SIMPLE_TRACKED_SWING,
                "target_public_trade_id": close.public_trade_id,
                "ticker": close.ticker,
                "expiry_input": close.expiry_input,
                "expiry_precision": (
                    close.expiry_precision.value if close.expiry_precision is not None else None
                ),
                "strike": str(close.strike) if close.strike is not None else None,
                "option_side": close.option_side,
                "action_price": (
                    str(close.reference_price) if close.reference_price is not None else None
                ),
                "entry_low": None,
                "entry_high": None,
                "avg_cost": None,
                "sl": None,
                "tp1": None,
                "tp2": None,
                "mentor_hint": None,
                "position_delta_eighths": None,
                "position_after_eighths": 0,
            }
        )
        return
    fast = parse_fast_signal(raw_text)
    if fast is not None:
        payload["ticker"] = fast.ticker
        payload["strike"] = float(fast.strike)
        payload["option_side"] = fast.option_side
        if fast.entry_price is not None:
            payload["entry_low"] = float(fast.entry_price)
            payload["entry_high"] = float(fast.entry_price)
            payload["action_price"] = None
        elif fast.warning and fast.warning.startswith("Ambiguous integer option premium"):
            payload["entry_low"] = None
            payload["entry_high"] = None
            payload["action_price"] = None
        payload["price_parse_confidence"] = (
            float(fast.price_parse_confidence) if fast.price_parse_confidence is not None else None
        )
        if fast.warning:
            payload["warnings"] = [*_unique_strings(payload.get("warnings")), fast.warning]
        if fast.expiry_precision is not None:
            payload["expiry_input"] = fast.expiry_input
            payload["expiry_precision"] = fast.expiry_precision.value
        elif (
            payload.get("intent") == "NEW_TRADE"
            and (fast.entry_price is not None or fast.warning is not None)
            and not re.search(r"\b(SWING|LEAPS?|波段|长期)\b", raw_text or "", re.IGNORECASE)
        ):
            payload["category_suggestion"] = "SHORT_TERM"

    source_input, source_precision = extract_expiry_input(raw_text)
    if source_precision is not None:
        payload["expiry_input"] = source_input
        payload["expiry_precision"] = source_precision.value

    normalized_input, normalized_precision = parse_expiry_input(payload.get("expiry_input"))
    if normalized_precision is not None:
        payload["expiry_input"] = normalized_input
        payload["expiry_precision"] = normalized_precision.value

    precision = payload.get("expiry_precision")
    if precision not in {item.value for item in ExpiryPrecision}:
        precision = None
    if precision is None and payload.get("category_suggestion") == "SHORT_TERM":
        payload["expiry_input"] = None
        payload["expiry_precision"] = ExpiryPrecision.AUTO_NEAREST.value
        payload["expiry_resolution_status"] = ExpiryResolutionStatus.UNRESOLVED.value
    candidate = payload.get("resolved_expiry")
    if candidate is not None:
        candidate_date = _date(candidate)
        if candidate_date is not None and candidate_date < date.today():
            payload["resolved_expiry"] = None
            payload["warnings"] = [
                *_unique_strings(payload.get("warnings")),
                "EXPIRY_IN_PAST_REQUIRES_REVIEW",
            ]
    payload["expiry"] = payload.get("resolved_expiry")
    if payload.get("category_suggestion") == "SWING" and payload.get("intent") == "NEW_TRADE":
        payload["_swing_mode"] = SIMPLE_TRACKED_SWING


def _apply_expiry_resolution(payload: dict[str, Any], result: ExpiryResolution) -> None:
    payload["expiry_input"] = result.expiry_input
    payload["expiry_precision"] = result.precision.value
    payload["resolved_expiry"] = (
        result.resolved_expiry.isoformat() if result.resolved_expiry else None
    )
    payload["expiry"] = payload["resolved_expiry"]
    payload["expiry_resolution_status"] = result.resolution_status.value
    payload["contract_validation_status"] = result.validation_status.value
    payload["option_contract_code"] = result.option_contract_code
    payload["expiry_candidates"] = [candidate.isoformat() for candidate in result.candidates]
    warnings = _unique_strings(payload.get("warnings"))
    warnings = [
        warning
        for warning in warnings
        if warning
        not in {
            "OPTION_CHAIN_UNAVAILABLE",
            "OPTION_CONTRACT_NOT_FOUND",
            "MULTIPLE_EXPIRATIONS_REQUIRE_MANAGER",
        }
    ]
    if result.warning:
        warnings.append(result.warning)
    payload["warnings"] = list(dict.fromkeys(warnings))


def _apply_position_ladder(payload: dict[str, Any]) -> None:
    if (
        payload.get("category_suggestion") == "SHORT_TERM"
        or payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
    ):
        payload["position_delta_eighths"] = None
        payload["position_after_eighths"] = None
        for field in (
            "plan_current_stock",
            "plan_starter",
            "plan_add_zone_low",
            "plan_add_zone_high",
            "plan_stock_sl",
            "plan_stock_pt1",
            "plan_stock_pt2",
            "plan_stock_pt3",
            "plan_fib_0618",
            "public_thesis",
        ):
            payload[field] = None
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
    if payload.get("expiry") is not None:
        missing = [field for field in missing if field != "expiry"]
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
        and payload.get("_swing_mode") != SIMPLE_TRACKED_SWING
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
        contract_resolver: OptionContractResolver | None = None,
        market_data_provider: MarketDataProvider | None = None,
    ) -> None:
        self.database = database
        self.attachment_store = attachment_store
        self.parser = parser
        self.contract_resolver = contract_resolver
        self.market_data_provider = market_data_provider

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
            _prepare_signal_payload(payload, source_snapshot[1])
            await self._match_simple_swing_close(payload, source_snapshot[0])
            await self._resolve_expiry(payload)
            await self._fill_missing_entry_price(payload)
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

    async def _match_simple_swing_close(self, payload: dict[str, Any], guild_id: int) -> None:
        if not (
            payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
            and payload.get("intent") == "UPDATE_TRADE"
            and payload.get("action") == "CLOSE"
        ):
            return
        async with self.database.session() as session:
            statement = select(Trade).where(
                Trade.guild_id == guild_id,
                Trade.category == "SWING",
                Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                Trade.state == "ACTIVE",
            )
            target_id = payload.get("target_public_trade_id")
            if target_id:
                statement = statement.where(Trade.public_trade_id == str(target_id).upper())
            else:
                statement = statement.where(
                    Trade.ticker == str(payload.get("ticker") or "").upper(),
                    Trade.strike == _decimal(payload.get("strike")),
                    Trade.option_side == _optional_enum(payload.get("option_side")),
                )
            candidates = list(await session.scalars(statement.order_by(Trade.public_trade_id)))
        expiry_input = str(payload.get("expiry_input") or "")
        if expiry_input and "/" in expiry_input:
            month, day = (int(part) for part in expiry_input.split("/"))
            candidates = [
                trade
                for trade in candidates
                if trade.expiry.month == month and trade.expiry.day == day
            ]
        elif expiry_input:
            try:
                exact = date.fromisoformat(expiry_input)
            except ValueError:
                exact = None
            if exact is not None:
                candidates = [trade for trade in candidates if trade.expiry == exact]
        payload["close_candidates"] = [trade.public_trade_id for trade in candidates]
        if len(candidates) != 1:
            payload["matched_trade_id"] = None
            payload["missing_fields"] = [
                *_unique_strings(payload.get("missing_fields")),
                "matched_trade",
            ]
            payload["warnings"] = [
                *_unique_strings(payload.get("warnings")),
                (
                    "SWING_CLOSE_NOT_FOUND"
                    if not candidates
                    else "MULTIPLE_SWING_CLOSE_MATCHES_REQUIRE_MANAGER"
                ),
            ]
            return
        trade = candidates[0]
        payload.update(
            {
                "matched_trade_id": str(trade.id),
                "target_public_trade_id": trade.public_trade_id,
                "ticker": trade.ticker,
                "expiry": trade.expiry.isoformat(),
                "resolved_expiry": trade.expiry.isoformat(),
                "expiry_input": trade.expiry.isoformat(),
                "expiry_precision": ExpiryPrecision.EXACT_DATE.value,
                "expiry_resolution_status": ExpiryResolutionStatus.EXPLICIT.value,
                "option_contract_code": trade.option_contract_code,
                "contract_validation_status": ContractValidationStatus.VALID.value,
                "strike": str(trade.strike),
                "option_side": trade.option_side,
            }
        )
        payload["missing_fields"] = [
            field
            for field in _unique_strings(payload.get("missing_fields"))
            if field not in {"matched_trade", "expiry", "contract"}
        ]

    async def _resolve_expiry(self, payload: dict[str, Any]) -> None:
        precision_value = payload.get("expiry_precision")
        if precision_value not in {item.value for item in ExpiryPrecision}:
            payload["contract_validation_status"] = ContractValidationStatus.UNVALIDATED.value
            return
        if self.contract_resolver is None:
            payload.setdefault(
                "contract_validation_status", ContractValidationStatus.UNVALIDATED.value
            )
            return
        ticker = payload.get("ticker")
        strike = _decimal(payload.get("strike"))
        option_side = _optional_enum(payload.get("option_side"))
        if not ticker or strike is None or option_side not in {"CALL", "PUT"}:
            payload["contract_validation_status"] = ContractValidationStatus.UNVALIDATED.value
            return
        result = await self.contract_resolver.resolve(
            ExpiryRequest(
                expiry_input=payload.get("expiry_input"),
                precision=ExpiryPrecision(str(precision_value)),
                ticker=str(ticker).upper(),
                strike=strike,
                option_side=option_side,
            )
        )
        _apply_expiry_resolution(payload, result)

    async def _fill_missing_entry_price(self, payload: dict[str, Any]) -> None:
        """Fill a completely missing ENTRY premium from a validated live option quote."""

        if self.market_data_provider is None:
            return
        if payload.get("intent") != "NEW_TRADE" or payload.get("action") != "ENTRY":
            return
        if any(
            payload.get(field) is not None for field in ("entry_low", "entry_high", "action_price")
        ):
            return
        if payload.get("contract_validation_status") != ContractValidationStatus.VALID.value:
            return
        underlying = str(payload.get("ticker") or "").strip().upper()
        underlying = underlying.removeprefix("US.").removeprefix("$")
        option_ticker = str(payload.get("option_contract_code") or "").strip().upper()
        if not underlying or not option_ticker:
            return

        request_key = f"signal-entry:{underlying}:{option_ticker}"
        try:
            prices = await self.market_data_provider.fetch_prices(
                (MarketPriceRequest(request_key, underlying, option_ticker),)
            )
            quote = next((item for item in prices if item.key == request_key), None)
            if quote is None or quote.price <= 0 or not quote.price.is_finite():
                raise ValueError("CURRENT_OPTION_QUOTE_UNAVAILABLE")
        except Exception as exc:
            code = str(getattr(exc, "code", "CURRENT_OPTION_QUOTE_UNAVAILABLE"))[:64]
            payload["_market_entry_price"] = {
                "status": "UNAVAILABLE",
                "error_code": code,
            }
            warnings = _unique_strings(payload.get("warnings"))
            warnings.append("CURRENT_OPTION_QUOTE_UNAVAILABLE")
            payload["warnings"] = list(dict.fromkeys(warnings))
            return

        price = str(quote.price)
        payload["entry_low"] = price
        payload["entry_high"] = price
        payload["action_price"] = None
        payload["missing_fields"] = [
            field
            for field in _unique_strings(payload.get("missing_fields"))
            if field != "entry_price"
        ]
        payload["_market_entry_price"] = {
            "status": "FILLED",
            "option_ticker": quote.option_ticker,
            "price": price,
            "price_source": quote.price_source,
            "source_timestamp": quote.source_timestamp.isoformat(),
            "received_at": quote.received_at.isoformat(),
            "market_status": quote.market_status,
        }
        warnings = _unique_strings(payload.get("warnings"))
        warnings = [
            warning for warning in warnings if warning != "CURRENT_OPTION_QUOTE_UNAVAILABLE"
        ]
        warnings.append("ENTRY_PRICE_FILLED_FROM_CURRENT_OPTION_QUOTE")
        payload["warnings"] = list(dict.fromkeys(warnings))

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
            matched_trade_id=(
                uuid.UUID(str(payload["matched_trade_id"]))
                if payload.get("matched_trade_id")
                else None
            ),
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
            expiry_input=payload.get("expiry_input"),
            expiry_precision=payload.get("expiry_precision"),
            expiry_resolution_status=str(
                payload.get("expiry_resolution_status", ExpiryResolutionStatus.UNRESOLVED.value)
            ),
            option_contract_code=payload.get("option_contract_code"),
            contract_validation_status=str(
                payload.get(
                    "contract_validation_status", ContractValidationStatus.UNVALIDATED.value
                )
            ),
            price_parse_confidence=_decimal(payload.get("price_parse_confidence")),
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
