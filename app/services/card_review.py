from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Mentor, SourceMessage, Trade, TradeDraft
from app.db.session import Database
from app.domain.enums import DraftStatus, TradeState
from app.domain.public_cards import PublicTradeCard
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
)
from app.services.swing_tracking import SIMPLE_TRACKED_SWING


class ReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReviewConflictError(ReviewError):
    pass


class ReviewValidationError(ReviewError):
    def __init__(self, code: str, missing_fields: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.missing_fields = missing_fields


@dataclass(frozen=True, slots=True)
class ReviewChoice:
    value: str
    label: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DraftEdit:
    intent: str
    action: str
    action_stage: str | None
    selected_category: str | None
    ticker: str | None
    expiry: date | None
    strike: Decimal | None
    option_side: str | None
    entry_low: Decimal | None
    entry_high: Decimal | None
    action_price: Decimal | None
    avg_cost: Decimal | None
    sl: Decimal | None
    tp1: Decimal | None
    tp2: Decimal | None
    current_pnl_pct: Decimal | None
    position_delta_eighths: int | None
    position_after_eighths: int | None
    current_stock: Decimal | None = None
    starter: Decimal | None = None
    add_zone_low: Decimal | None = None
    add_zone_high: Decimal | None = None
    stock_sl: Decimal | None = None
    stock_pt1: Decimal | None = None
    stock_pt2: Decimal | None = None
    stock_pt3: Decimal | None = None
    fib_0618: Decimal | None = None
    public_thesis: str | None = None
    replace_plan: bool = False


@dataclass(frozen=True, slots=True)
class ShortTermDraftEdit:
    selected_category: str
    ticker: str
    expiry_input: str | None
    strike: Decimal
    option_side: str
    entry_price: Decimal


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    id: uuid.UUID
    guild_id: int
    draft_code: str
    status: str
    intent: str
    action: str
    action_stage: str | None
    category_suggestion: str | None
    selected_category: str | None
    ticker: str | None
    expiry: date | None
    expiry_input: str | None
    expiry_precision: str | None
    expiry_resolution_status: str
    option_contract_code: str | None
    contract_validation_status: str
    price_parse_confidence: Decimal | None
    expiry_candidates: tuple[date, ...]
    expiry_metadata_legacy: bool
    strike: Decimal | None
    option_side: str | None
    entry_low: Decimal | None
    entry_high: Decimal | None
    action_price: Decimal | None
    avg_cost: Decimal | None
    sl: Decimal | None
    tp1: Decimal | None
    tp2: Decimal | None
    position_delta_eighths: int | None
    position_after_eighths: int | None
    current_pnl_pct: Decimal | None
    mentor_hint: str | None
    mentor_id: uuid.UUID | None
    mentor_name: str | None
    matched_trade_id: uuid.UUID | None
    matched_trade_code: str | None
    parser_confidence: Decimal | None
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    internal_notes: str | None
    reviewed_by: int | None
    review_channel_id: int | None
    review_message_id: int | None
    version: int
    current_stock: Decimal | None
    starter: Decimal | None
    add_zone_low: Decimal | None
    add_zone_high: Decimal | None
    stock_sl: Decimal | None
    stock_pt1: Decimal | None
    stock_pt2: Decimal | None
    stock_pt3: Decimal | None
    fib_0618: Decimal | None
    public_thesis: str | None
    is_lotto: bool
    swing_mode: str | None = None
    personal_follow_override: bool | None = None


ACTIVE_REVIEW_STATUSES = {
    DraftStatus.PENDING_REVIEW.value,
    DraftStatus.PARSE_FAILED.value,
}
REGISTERED_REVIEW_STATUSES = {
    *ACTIVE_REVIEW_STATUSES,
    DraftStatus.READY.value,
    DraftStatus.PUBLISH_FAILED.value,
}

MISSING_FIELD_LABELS = {
    "intent": "订单类型",
    "category": "Category",
    "ticker": "Ticker",
    "expiry": "Expiry",
    "strike": "Strike",
    "option_side": "Call / Put",
    "contract": "有效期权合约",
    "entry_price": "入场价",
    "mentor": "Mentor",
    "matched_trade": "关联已有订单",
    "action": "本次操作",
    "add_stage": "第几次加仓",
    "action_price": "本次操作价格",
    "update_content": "至少一项订单更新",
    "position_after_eighths": "操作后总持仓",
    "manual_review": "手动检查",
}


def missing_field_labels(fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(MISSING_FIELD_LABELS.get(field, field) for field in fields)


def publication_missing_fields(draft: TradeDraft | ReviewDraft) -> tuple[str, ...]:
    missing: list[str] = []
    category = draft.selected_category or draft.category_suggestion
    swing_mode = (
        draft.parse_payload.get("_swing_mode")
        if isinstance(draft, TradeDraft)
        else draft.swing_mode
    )
    if category == "SWING" and swing_mode == SIMPLE_TRACKED_SWING:
        if draft.selected_category != "SWING":
            missing.append("category")
        if draft.intent == "NEW_TRADE" and draft.action == "ENTRY":
            for field in ("ticker", "expiry", "strike", "option_side"):
                value = getattr(draft, field)
                if value is None or (field == "expiry" and value < date.today()):
                    missing.append(field)
            if getattr(draft, "contract_validation_status", None) in {
                ContractValidationStatus.NOT_FOUND.value,
                ContractValidationStatus.UNAVAILABLE.value,
            }:
                missing.append("contract")
            if draft.entry_low is None and draft.entry_high is None and draft.action_price is None:
                missing.append("entry_price")
        elif draft.intent == "UPDATE_TRADE" and draft.action == "CLOSE":
            matched = (
                draft.matched_trade_id
                if isinstance(draft, TradeDraft)
                else draft.matched_trade_code
            )
            if matched is None:
                missing.append("matched_trade")
        else:
            missing.append("action")
        return tuple(missing)
    if category == "SHORT_TERM":
        if draft.intent != "NEW_TRADE":
            missing.append("intent")
        if draft.selected_category != "SHORT_TERM":
            missing.append("category")
        for field in ("ticker", "expiry", "strike", "option_side"):
            value = getattr(draft, field)
            if value is None or (field == "expiry" and value < date.today()):
                missing.append(field)
        if getattr(draft, "expiry_precision", None) is not None and getattr(
            draft, "contract_validation_status", None
        ) in {
            ContractValidationStatus.NOT_FOUND.value,
            ContractValidationStatus.UNAVAILABLE.value,
        }:
            missing.append("contract")
        if draft.entry_low is None and draft.entry_high is None and draft.action_price is None:
            missing.append("entry_price")
        return tuple(missing)

    if draft.intent not in {"NEW_TRADE", "UPDATE_TRADE"}:
        missing.append("intent")
    mentor_missing = (
        draft.mentor_id is None if isinstance(draft, TradeDraft) else draft.mentor_name is None
    )
    if mentor_missing:
        missing.append("mentor")

    if draft.intent == "NEW_TRADE":
        if draft.selected_category is None:
            missing.append("category")
        for field in ("ticker", "expiry", "strike", "option_side"):
            value = getattr(draft, field)
            if value is None or (field == "expiry" and value < date.today()):
                missing.append(field)
        if getattr(draft, "expiry_precision", None) is not None and getattr(
            draft, "contract_validation_status", None
        ) in {
            ContractValidationStatus.NOT_FOUND.value,
            ContractValidationStatus.UNAVAILABLE.value,
        }:
            missing.append("contract")
        if draft.entry_low is None and draft.entry_high is None and draft.action_price is None:
            missing.append("entry_price")
        if draft.position_after_eighths is None:
            missing.append("position_after_eighths")
    elif draft.intent == "UPDATE_TRADE":
        matched = (
            draft.matched_trade_id if isinstance(draft, TradeDraft) else draft.matched_trade_code
        )
        if matched is None:
            missing.append("matched_trade")
        if draft.action in {"", "UNKNOWN"}:
            missing.append("action")
        if draft.action == "ADD" and draft.action_stage not in {
            "FIRST",
            "SECOND",
            "THIRD",
            "FOURTH",
        }:
            missing.append("add_stage")
        if draft.action in {"ADD", "TP1", "TP2", "PARTIAL_SL", "SL", "CLOSE", "ROLL"}:
            if draft.action_price is None:
                missing.append("action_price")
        elif all(
            value is None
            for value in (
                draft.action_price,
                draft.avg_cost,
                draft.sl,
                draft.tp1,
                draft.tp2,
                draft.current_pnl_pct,
            )
        ):
            missing.append("update_content")
        if draft.position_after_eighths is None:
            missing.append("position_after_eighths")
    return tuple(missing)


def public_preview_payload(draft: ReviewDraft) -> PublicTradeCard:
    """Copy only explicitly public fields into the member-card boundary."""

    return PublicTradeCard(
        public_trade_id=None,
        category=draft.selected_category or draft.category_suggestion or "SHORT_TERM",
        action=draft.action,
        action_stage=draft.action_stage,
        ticker=draft.ticker,
        expiry=draft.expiry,
        strike=draft.strike,
        option_side=draft.option_side,
        entry_low=draft.entry_low,
        entry_high=draft.entry_high,
        action_price=draft.action_price,
        avg_cost=draft.avg_cost,
        sl=draft.sl,
        tp1=draft.tp1,
        tp2=draft.tp2,
        position_delta_eighths=draft.position_delta_eighths,
        position_after_eighths=draft.position_after_eighths or 0,
        pnl_pct=draft.current_pnl_pct,
        current_stock=draft.current_stock,
        starter=draft.starter,
        add_zone_low=draft.add_zone_low,
        add_zone_high=draft.add_zone_high,
        stock_sl=draft.stock_sl,
        stock_pt1=draft.stock_pt1,
        stock_pt2=draft.stock_pt2,
        stock_pt3=draft.stock_pt3,
        fib_0618=draft.fib_0618,
        public_thesis=draft.public_thesis,
        is_lotto=draft.is_lotto,
    )


def _plan_decimal(payload: dict[str, object], field: str) -> Decimal | None:
    value = payload.get(field)
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _public_thesis(payload: dict[str, object]) -> str | None:
    value = payload.get("public_thesis")
    if not isinstance(value, str):
        return None
    rendered = " ".join(value.split()).strip()
    return rendered[:300] or None


def _expiry_candidates(payload: dict[str, object]) -> tuple[date, ...]:
    raw = payload.get("expiry_candidates")
    if not isinstance(raw, list):
        return ()
    candidates = []
    for value in raw:
        try:
            candidates.append(date.fromisoformat(str(value)))
        except ValueError:
            continue
    return tuple(dict.fromkeys(candidates))


def _audit_payload(draft: TradeDraft) -> dict[str, object]:
    return {
        "status": draft.status,
        "version": draft.version,
        "mentor_id": str(draft.mentor_id) if draft.mentor_id else None,
        "matched_trade_id": str(draft.matched_trade_id) if draft.matched_trade_id else None,
        "intent": draft.intent,
        "action": draft.action,
        "action_stage": draft.action_stage,
        "selected_category": draft.selected_category,
        "ticker": draft.ticker,
        "expiry": draft.expiry.isoformat() if draft.expiry else None,
        "expiry_input": draft.expiry_input,
        "expiry_precision": draft.expiry_precision,
        "expiry_resolution_status": draft.expiry_resolution_status,
        "option_contract_code": draft.option_contract_code,
        "contract_validation_status": draft.contract_validation_status,
        "strike": str(draft.strike) if draft.strike is not None else None,
        "option_side": draft.option_side,
        "entry_low": str(draft.entry_low) if draft.entry_low is not None else None,
        "entry_high": str(draft.entry_high) if draft.entry_high is not None else None,
        "action_price": str(draft.action_price) if draft.action_price is not None else None,
        "avg_cost": str(draft.avg_cost) if draft.avg_cost is not None else None,
        "sl": str(draft.sl) if draft.sl is not None else None,
        "tp1": str(draft.tp1) if draft.tp1 is not None else None,
        "tp2": str(draft.tp2) if draft.tp2 is not None else None,
        "position_delta_eighths": draft.position_delta_eighths,
        "position_after_eighths": draft.position_after_eighths,
        "current_pnl_pct": (
            str(draft.current_pnl_pct) if draft.current_pnl_pct is not None else None
        ),
        "plan_current_stock": draft.parse_payload.get("plan_current_stock"),
        "plan_starter": draft.parse_payload.get("plan_starter"),
        "plan_add_zone_low": draft.parse_payload.get("plan_add_zone_low"),
        "plan_add_zone_high": draft.parse_payload.get("plan_add_zone_high"),
        "plan_stock_sl": draft.parse_payload.get("plan_stock_sl"),
        "plan_stock_pt1": draft.parse_payload.get("plan_stock_pt1"),
        "plan_stock_pt2": draft.parse_payload.get("plan_stock_pt2"),
        "plan_stock_pt3": draft.parse_payload.get("plan_stock_pt3"),
        "plan_fib_0618": draft.parse_payload.get("plan_fib_0618"),
        "public_thesis": draft.parse_payload.get("public_thesis"),
        "is_lotto": draft.is_lotto,
    }


class CardReviewService:
    def __init__(
        self,
        database: Database,
        contract_resolver: OptionContractResolver | None = None,
    ) -> None:
        self.database = database
        self.contract_resolver = contract_resolver

    async def get(self, draft_id: uuid.UUID) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await session.get(TradeDraft, draft_id)
            if draft is None:
                raise ReviewError("DRAFT_NOT_FOUND")
            return await self._snapshot(session, draft)

    async def ensure_expiry_resolution(
        self,
        draft_id: uuid.UUID,
        *,
        expected_version: int | None = None,
        force: bool = False,
    ) -> ReviewDraft:
        current = await self.get(draft_id)
        if expected_version is not None and current.version != expected_version:
            raise ReviewConflictError("DRAFT_VERSION_CONFLICT")
        if self.contract_resolver is None:
            return current
        if (
            not force
            and current.expiry is not None
            and current.contract_validation_status == ContractValidationStatus.VALID.value
        ):
            return current
        request = await self._expiry_request(current)
        if request is None:
            return current
        result = await self.contract_resolver.resolve(request)
        return await self._persist_expiry_resolution(
            current.id,
            result=result,
            expected_version=current.version,
            actor_user_id=None,
            interaction_id=None,
            action_type="TRADE_DRAFT_EXPIRY_AUTO_RESOLVED",
        )

    async def select_expiry(
        self,
        draft_id: uuid.UUID,
        *,
        selection: str,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        if self.contract_resolver is None:
            raise ReviewValidationError("OPTION_CHAIN_UNAVAILABLE")
        current = await self.get(draft_id)
        if current.version != expected_version:
            raise ReviewConflictError("DRAFT_VERSION_CONFLICT")
        if current.ticker is None or current.strike is None or current.option_side is None:
            raise ReviewValidationError("CONTRACT_FIELDS_REQUIRED")
        if selection in {"ZERO_DTE", "AUTO_NEAREST"}:
            if (current.selected_category or current.category_suggestion) != "SHORT_TERM":
                raise ReviewValidationError("SHORT_TERM_EXPIRY_MODE_REQUIRED")
            precision = ExpiryPrecision(selection)
            expiry_input = "0DTE" if precision is ExpiryPrecision.ZERO_DTE else None
            result = await self.contract_resolver.resolve(
                ExpiryRequest(
                    expiry_input=expiry_input,
                    precision=precision,
                    ticker=current.ticker,
                    strike=current.strike,
                    option_side=current.option_side,
                )
            )
        elif selection.startswith("DATE:"):
            try:
                selected_date = date.fromisoformat(selection.removeprefix("DATE:"))
            except ValueError as exc:
                raise ReviewValidationError("EXPIRY_INVALID") from exc
            result = await self.contract_resolver.validate_exact(
                ticker=current.ticker,
                expiry=selected_date,
                strike=current.strike,
                option_side=current.option_side,
                manager_confirmed=True,
            )
        else:
            raise ReviewValidationError("EXPIRY_SELECTION_INVALID")
        if result.validation_status is not ContractValidationStatus.VALID:
            raise ReviewValidationError(
                "CONTRACT_NOT_FOUND"
                if result.validation_status is ContractValidationStatus.NOT_FOUND
                else "OPTION_CHAIN_UNAVAILABLE"
            )
        return await self._persist_expiry_resolution(
            current.id,
            result=result,
            expected_version=current.version,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
            action_type="TRADE_DRAFT_EXPIRY_SELECTED",
        )

    async def next_unposted(self, guild_id: int) -> ReviewDraft | None:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(TradeDraft)
                .where(
                    TradeDraft.guild_id == guild_id,
                    TradeDraft.status.in_(ACTIVE_REVIEW_STATUSES),
                    TradeDraft.review_message_id.is_(None),
                )
                .order_by(TradeDraft.created_at, TradeDraft.id)
                .limit(1)
            )
            return await self._snapshot(session, draft) if draft is not None else None

    async def registered(self, guild_id: int) -> list[ReviewDraft]:
        async with self.database.session() as session:
            drafts = (
                await session.scalars(
                    select(TradeDraft)
                    .where(
                        TradeDraft.guild_id == guild_id,
                        TradeDraft.status.in_(REGISTERED_REVIEW_STATUSES),
                        TradeDraft.review_message_id.is_not(None),
                    )
                    .order_by(TradeDraft.created_at, TradeDraft.id)
                )
            ).all()
            return [await self._snapshot(session, draft) for draft in drafts]

    async def published_without_review_message(self, guild_id: int) -> list[ReviewDraft]:
        """Repair terminal cards whose Discord reference was accidentally cleared."""

        async with self.database.session() as session:
            drafts = (
                await session.scalars(
                    select(TradeDraft)
                    .where(
                        TradeDraft.guild_id == guild_id,
                        TradeDraft.status == DraftStatus.PUBLISHED.value,
                        TradeDraft.review_channel_id.is_not(None),
                        TradeDraft.review_message_id.is_(None),
                    )
                    .order_by(TradeDraft.updated_at, TradeDraft.id)
                )
            ).all()
            return [await self._snapshot(session, draft) for draft in drafts]

    async def attach_review_message(
        self,
        draft_id: uuid.UUID,
        *,
        channel_id: int,
        message_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await session.get(TradeDraft, draft_id)
            if draft is None:
                raise ReviewError("DRAFT_NOT_FOUND")
            if draft.review_message_id is None:
                draft.review_channel_id = channel_id
                draft.review_message_id = message_id
                await session.commit()
            return await self._snapshot(session, draft)

    async def mentor_choices(self, guild_id: int) -> list[ReviewChoice]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(Mentor.id, Mentor.name, Mentor.short_code)
                    .where(Mentor.guild_id == guild_id, Mentor.is_active.is_(True))
                    .order_by(Mentor.name)
                    .limit(25)
                )
            ).all()
        return [
            ReviewChoice(str(mentor_id), name[:100], f"Code: {short_code}"[:100])
            for mentor_id, name, short_code in rows
        ]

    async def trade_choices(
        self, guild_id: int, *, simple_swing_only: bool = False
    ) -> list[ReviewChoice]:
        async with self.database.session() as session:
            statement = (
                select(Trade.id, Trade.public_trade_id, Trade.ticker, Trade.option_side)
                .where(
                    Trade.guild_id == guild_id,
                    Trade.category.in_(("SWING", "LEAPS")),
                    Trade.state.in_([TradeState.ACTIVE.value, TradeState.RUNNER.value]),
                )
                .order_by(Trade.updated_at.desc())
                .limit(25)
            )
            if simple_swing_only:
                statement = statement.where(
                    Trade.category == "SWING",
                    Trade.tracking_mode == SIMPLE_TRACKED_SWING,
                    Trade.state == TradeState.ACTIVE.value,
                )
            rows = (await session.execute(statement)).all()
        return [
            ReviewChoice(str(trade_id), public_id[:100], f"{ticker} · {side}"[:100])
            for trade_id, public_id, ticker, side in rows
        ]

    async def select_mentor(
        self,
        draft_id: uuid.UUID,
        *,
        mentor_id: uuid.UUID,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            if (draft.selected_category or draft.category_suggestion) == "SHORT_TERM" or (
                draft.parse_payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
            ):
                raise ReviewValidationError("TRACKED_TRADE_MENTOR_FORBIDDEN")
            mentor = await session.get(Mentor, mentor_id)
            if mentor is None or mentor.guild_id != draft.guild_id or not mentor.is_active:
                raise ReviewValidationError("MENTOR_UNAVAILABLE")
            before = _audit_payload(draft)
            draft.mentor_id = mentor.id
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "TRADE_DRAFT_MENTOR_SELECTED", before
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def select_trade(
        self,
        draft_id: uuid.UUID,
        *,
        trade_id: uuid.UUID,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            if (draft.selected_category or draft.category_suggestion) == "SHORT_TERM":
                raise ReviewValidationError("SHORT_TERM_TRADE_LINK_FORBIDDEN")
            trade = await session.get(Trade, trade_id)
            simple_swing = draft.parse_payload.get("_swing_mode") == SIMPLE_TRACKED_SWING
            if (
                trade is None
                or trade.guild_id != draft.guild_id
                or trade.category == "SHORT_TERM"
                or (
                    simple_swing
                    and (
                        trade.category != "SWING"
                        or trade.tracking_mode != SIMPLE_TRACKED_SWING
                        or trade.state != TradeState.ACTIVE.value
                    )
                )
            ):
                raise ReviewValidationError("TRADE_UNAVAILABLE")
            before = _audit_payload(draft)
            draft.matched_trade_id = trade.id
            draft.is_lotto = trade.is_lotto
            if simple_swing:
                draft.selected_category = "SWING"
                draft.category_suggestion = "SWING"
                draft.intent = "UPDATE_TRADE"
                draft.action = "CLOSE"
                draft.ticker = trade.ticker
                draft.expiry = trade.expiry
                draft.expiry_input = trade.expiry.isoformat()
                draft.expiry_precision = ExpiryPrecision.EXACT_DATE.value
                draft.option_contract_code = trade.option_contract_code
                draft.contract_validation_status = ContractValidationStatus.VALID.value
                draft.strike = trade.strike
                draft.option_side = trade.option_side
                draft.position_after_eighths = 0
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "TRADE_DRAFT_TRADE_SELECTED", before
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def toggle_lotto(
        self,
        draft_id: uuid.UUID,
        *,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == draft_id).with_for_update()
            )
            if draft is None:
                raise ReviewError("DRAFT_NOT_FOUND")
            if draft.status not in REGISTERED_REVIEW_STATUSES:
                raise ReviewValidationError("DRAFT_NOT_EDITABLE")
            self._assert_version(draft, expected_version)
            before = _audit_payload(draft)
            draft.is_lotto = not draft.is_lotto
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session,
                draft,
                actor_user_id,
                interaction_id,
                "TRADE_DRAFT_LOTTO_TOGGLED",
                before,
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def cycle_personal_follow_override(
        self,
        draft_id: uuid.UUID,
        *,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            before = _audit_payload(draft)
            payload = dict(draft.parse_payload)
            current = payload.get("_personal_follow_override")
            if current is None:
                payload["_personal_follow_override"] = True
            elif current is True:
                payload["_personal_follow_override"] = False
            else:
                payload.pop("_personal_follow_override", None)
            draft.parse_payload = payload
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session,
                draft,
                actor_user_id,
                interaction_id,
                "PERSONAL_FOLLOW_OVERRIDE_CHANGED",
                before,
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def select_category(
        self,
        draft_id: uuid.UUID,
        *,
        category: str,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        if category not in {"SHORT_TERM", "SWING", "LEAPS"}:
            raise ReviewValidationError("CATEGORY_INVALID")
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            if draft.selected_category == category:
                return await self._snapshot(session, draft)
            before = _audit_payload(draft)
            draft.selected_category = category
            if category in {"SHORT_TERM", "SWING"}:
                self._clear_short_term_fields(draft)
                payload = dict(draft.parse_payload)
                if category == "SWING":
                    payload["_swing_mode"] = SIMPLE_TRACKED_SWING
                else:
                    payload.pop("_swing_mode", None)
                draft.parse_payload = payload
                if (
                    category == "SWING"
                    and draft.expiry_precision == ExpiryPrecision.AUTO_NEAREST.value
                ):
                    draft.expiry = None
                    draft.expiry_input = None
                    draft.expiry_precision = None
                    draft.expiry_resolution_status = ExpiryResolutionStatus.UNRESOLVED.value
                    draft.option_contract_code = None
                    draft.contract_validation_status = ContractValidationStatus.UNVALIDATED.value
                if draft.expiry_precision is None:
                    if draft.expiry is not None:
                        draft.expiry_input = draft.expiry.isoformat()
                        draft.expiry_precision = ExpiryPrecision.EXACT_DATE.value
                    else:
                        draft.expiry_input = None
                        draft.expiry_precision = ExpiryPrecision.AUTO_NEAREST.value
            elif draft.expiry_precision == ExpiryPrecision.AUTO_NEAREST.value:
                draft.expiry = None
                draft.expiry_input = None
                draft.expiry_precision = None
                draft.expiry_resolution_status = ExpiryResolutionStatus.UNRESOLVED.value
                draft.option_contract_code = None
                draft.contract_validation_status = ContractValidationStatus.UNVALIDATED.value
            if category == "LEAPS":
                payload = dict(draft.parse_payload)
                payload.pop("_swing_mode", None)
                draft.parse_payload = payload
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session,
                draft,
                actor_user_id,
                interaction_id,
                "TRADE_DRAFT_CATEGORY_SELECTED",
                before,
            )
            await session.commit()
            updated = await self._snapshot(session, draft)
        if category in {"SHORT_TERM", "SWING"}:
            return await self.ensure_expiry_resolution(
                updated.id,
                expected_version=updated.version,
                force=True,
            )
        return updated

    async def select_operation(
        self,
        draft_id: uuid.UUID,
        *,
        intent: str,
        action: str,
        action_stage: str | None,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        if intent not in {"NEW_TRADE", "UPDATE_TRADE"}:
            raise ReviewValidationError("INTENT_INVALID")
        if intent == "NEW_TRADE":
            if action != "ENTRY" or action_stage not in {None, "NONE"}:
                raise ReviewValidationError("OPERATION_INVALID")
            action_stage = "NONE"
        elif action not in {
            "ADD",
            "UPDATE",
            "TP1",
            "TP2",
            "RUNNER",
            "PARTIAL_SL",
            "SL",
            "CLOSE",
            "CANCEL",
            "ROLL",
        }:
            raise ReviewValidationError("ACTION_INVALID")
        elif action == "ADD" and action_stage not in {
            "FIRST",
            "SECOND",
            "THIRD",
            "FOURTH",
        }:
            raise ReviewValidationError("ADD_STAGE_REQUIRED")
        elif action != "ADD":
            action_stage = "NONE"

        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            before = _audit_payload(draft)
            was_new_entry = draft.intent == "NEW_TRADE" and draft.action == "ENTRY"
            draft.intent = intent
            draft.action = action
            draft.action_stage = action_stage
            if intent == "NEW_TRADE":
                draft.matched_trade_id = None
                if not was_new_entry or draft.position_after_eighths is None:
                    draft.position_delta_eighths = 1
                    draft.position_after_eighths = 1
            elif action == "ADD":
                suggested_after = {
                    "FIRST": 2,
                    "SECOND": 4,
                    "THIRD": 6,
                    "FOURTH": 8,
                }[action_stage]
                draft.position_delta_eighths = None
                draft.position_after_eighths = suggested_after
            elif action in {"SL", "CLOSE", "CANCEL"}:
                draft.position_delta_eighths = None
                draft.position_after_eighths = 0
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session,
                draft,
                actor_user_id,
                interaction_id,
                "TRADE_DRAFT_OPERATION_SELECTED",
                before,
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def edit_short_term(
        self,
        draft_id: uuid.UUID,
        *,
        values: ShortTermDraftEdit,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        self._validate_short_term_edit(values)
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            before = _audit_payload(draft)
            draft.selected_category = values.selected_category
            draft.category_suggestion = values.selected_category
            draft.intent = "NEW_TRADE"
            draft.action = "ENTRY"
            draft.action_stage = None
            draft.ticker = values.ticker
            draft.strike = values.strike
            draft.option_side = values.option_side
            expiry_input, precision = parse_expiry_input(values.expiry_input)
            if precision is None:
                if values.selected_category == "SWING":
                    raise ReviewValidationError("SWING_EXPIRY_REQUIRED")
                expiry_input = None
                precision = ExpiryPrecision.AUTO_NEAREST
            draft.expiry = None
            draft.expiry_input = expiry_input
            draft.expiry_precision = precision.value
            draft.expiry_resolution_status = ExpiryResolutionStatus.UNRESOLVED.value
            draft.option_contract_code = None
            draft.contract_validation_status = ContractValidationStatus.UNVALIDATED.value
            draft.entry_low = values.entry_price
            draft.entry_high = values.entry_price
            draft.action_price = None
            draft.mentor_id = None
            draft.matched_trade_id = None
            draft.position_delta_eighths = None
            draft.position_after_eighths = None
            draft.avg_cost = None
            draft.sl = None
            draft.tp1 = None
            draft.tp2 = None
            draft.current_pnl_pct = None
            payload = dict(draft.parse_payload)
            if values.selected_category == "SWING":
                payload["_swing_mode"] = SIMPLE_TRACKED_SWING
            else:
                payload.pop("_swing_mode", None)
            draft.parse_payload = payload
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "SHORT_TERM_DRAFT_EDITED", before
            )
            await session.commit()
            updated = await self._snapshot(session, draft)
        return await self.ensure_expiry_resolution(
            updated.id,
            expected_version=updated.version,
            force=True,
        )

    async def edit(
        self,
        draft_id: uuid.UUID,
        *,
        values: DraftEdit,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        self._validate_edit(values)
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            before = _audit_payload(draft)
            for field in (
                "intent",
                "action",
                "action_stage",
                "selected_category",
                "ticker",
                "expiry",
                "strike",
                "option_side",
                "entry_low",
                "entry_high",
                "action_price",
                "avg_cost",
                "sl",
                "tp1",
                "tp2",
                "current_pnl_pct",
                "position_delta_eighths",
                "position_after_eighths",
            ):
                setattr(draft, field, getattr(values, field))
            if values.expiry is not None:
                draft.expiry_input = values.expiry.isoformat()
                draft.expiry_precision = ExpiryPrecision.EXACT_DATE.value
                draft.expiry_resolution_status = ExpiryResolutionStatus.EXPLICIT.value
            else:
                draft.expiry_input = None
                draft.expiry_precision = None
                draft.expiry_resolution_status = ExpiryResolutionStatus.UNRESOLVED.value
            draft.option_contract_code = None
            draft.contract_validation_status = ContractValidationStatus.UNVALIDATED.value
            if values.replace_plan:
                payload = dict(draft.parse_payload)
                for attribute, key in (
                    ("current_stock", "plan_current_stock"),
                    ("starter", "plan_starter"),
                    ("add_zone_low", "plan_add_zone_low"),
                    ("add_zone_high", "plan_add_zone_high"),
                    ("stock_sl", "plan_stock_sl"),
                    ("stock_pt1", "plan_stock_pt1"),
                    ("stock_pt2", "plan_stock_pt2"),
                    ("stock_pt3", "plan_stock_pt3"),
                    ("fib_0618", "plan_fib_0618"),
                ):
                    value = getattr(values, attribute)
                    payload[key] = float(value) if value is not None else None
                payload["public_thesis"] = values.public_thesis
                draft.parse_payload = payload
            if draft.selected_category == "SHORT_TERM":
                self._clear_short_term_fields(draft)
            self._mark_edited(draft, actor_user_id)
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "TRADE_DRAFT_EDITED", before
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def approve(
        self,
        draft_id: uuid.UUID,
        *,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        validated: ExpiryResolution | None = None
        if self.contract_resolver is not None:
            current = await self.get(draft_id)
            if current.version != expected_version:
                raise ReviewConflictError("DRAFT_VERSION_CONFLICT")
            if (
                current.intent == "NEW_TRADE"
                and current.ticker is not None
                and current.expiry is not None
                and current.strike is not None
                and current.option_side in {"CALL", "PUT"}
            ):
                validated = await self.contract_resolver.validate_exact(
                    ticker=current.ticker,
                    expiry=current.expiry,
                    strike=current.strike,
                    option_side=current.option_side,
                    manager_confirmed=(
                        current.expiry_resolution_status
                        == ExpiryResolutionStatus.MANAGER_CONFIRMED.value
                    ),
                )
                if validated.validation_status is not ContractValidationStatus.VALID:
                    code = (
                        "CONTRACT_NOT_FOUND"
                        if validated.validation_status is ContractValidationStatus.NOT_FOUND
                        else "OPTION_CHAIN_UNAVAILABLE"
                    )
                    raise ReviewValidationError(code)
        async with self.database.session() as session:
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == draft_id).with_for_update()
            )
            if draft is None:
                raise ReviewError("DRAFT_NOT_FOUND")
            if draft.status in {
                DraftStatus.READY.value,
                DraftStatus.PUBLISH_FAILED.value,
                DraftStatus.PUBLISHED.value,
            }:
                return await self._snapshot(session, draft)
            self._assert_editable(draft)
            self._assert_version(draft, expected_version)
            if validated is not None:
                self._apply_resolution_to_draft(draft, validated)
            missing = publication_missing_fields(draft)
            if missing:
                raise ReviewValidationError("DRAFT_INCOMPLETE", missing)
            if (
                (draft.selected_category or draft.category_suggestion) in {"SWING", "LEAPS"}
                and draft.parse_payload.get("_swing_mode") != SIMPLE_TRACKED_SWING
                and draft.intent == "NEW_TRADE"
                and draft.action == "ENTRY"
            ):
                self._validate_plan_fields(
                    option_side=draft.option_side,
                    current_stock=_plan_decimal(draft.parse_payload, "plan_current_stock"),
                    starter=_plan_decimal(draft.parse_payload, "plan_starter"),
                    add_zone_low=_plan_decimal(draft.parse_payload, "plan_add_zone_low"),
                    add_zone_high=_plan_decimal(draft.parse_payload, "plan_add_zone_high"),
                    stock_sl=_plan_decimal(draft.parse_payload, "plan_stock_sl"),
                    stock_pt1=_plan_decimal(draft.parse_payload, "plan_stock_pt1"),
                    stock_pt2=_plan_decimal(draft.parse_payload, "plan_stock_pt2"),
                    stock_pt3=_plan_decimal(draft.parse_payload, "plan_stock_pt3"),
                    fib_0618=_plan_decimal(draft.parse_payload, "plan_fib_0618"),
                )
            await self._validate_position_transition(session, draft)
            before = _audit_payload(draft)
            draft.status = DraftStatus.READY.value
            draft.reviewed_by = actor_user_id
            draft.version += 1
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "TRADE_DRAFT_APPROVED", before
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def delete(
        self,
        draft_id: uuid.UUID,
        *,
        expected_version: int,
        actor_user_id: int,
        interaction_id: int,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await session.scalar(
                select(TradeDraft).where(TradeDraft.id == draft_id).with_for_update()
            )
            if draft is None:
                raise ReviewError("DRAFT_NOT_FOUND")
            if draft.status == DraftStatus.DELETED.value:
                return await self._snapshot(session, draft)
            if draft.status == DraftStatus.PUBLISHED.value:
                raise ReviewValidationError("PUBLISHED_DRAFT_LOCKED")
            self._assert_version(draft, expected_version)
            before = _audit_payload(draft)
            draft.status = DraftStatus.DELETED.value
            draft.reviewed_by = actor_user_id
            draft.version += 1
            await self._add_audit(
                session, draft, actor_user_id, interaction_id, "TRADE_DRAFT_DELETED", before
            )
            await session.commit()
            return await self._snapshot(session, draft)

    async def _expiry_request(self, draft: ReviewDraft) -> ExpiryRequest | None:
        if draft.ticker is None or draft.strike is None or draft.option_side not in {"CALL", "PUT"}:
            return None
        if draft.expiry_metadata_legacy and draft.expiry_precision in {
            None,
            ExpiryPrecision.EXACT_DATE.value,
        }:
            async with self.database.session() as session:
                raw_text = await session.scalar(
                    select(SourceMessage.raw_text)
                    .join(TradeDraft, TradeDraft.source_message_id == SourceMessage.id)
                    .where(TradeDraft.id == draft.id)
                )
            expiry_input, source_precision = extract_expiry_input(raw_text)
            fast = parse_fast_signal(raw_text)
            if fast is not None and fast.expiry_precision is not None:
                expiry_input = fast.expiry_input
                source_precision = fast.expiry_precision
            if source_precision is not None:
                return ExpiryRequest(
                    expiry_input=expiry_input,
                    precision=source_precision,
                    ticker=draft.ticker,
                    strike=draft.strike,
                    option_side=draft.option_side,
                )
            if draft.expiry is not None and (
                draft.expiry.year < self.contract_resolver.today.year
                or draft.expiry.year > self.contract_resolver.today.year + 10
            ):
                return ExpiryRequest(
                    expiry_input=f"{draft.expiry.month}/{draft.expiry.day}",
                    precision=ExpiryPrecision.MONTH_DAY,
                    ticker=draft.ticker,
                    strike=draft.strike,
                    option_side=draft.option_side,
                )
            if (draft.selected_category or draft.category_suggestion) == "SHORT_TERM":
                return ExpiryRequest(
                    expiry_input=None,
                    precision=ExpiryPrecision.AUTO_NEAREST,
                    ticker=draft.ticker,
                    strike=draft.strike,
                    option_side=draft.option_side,
                )
        precision_value = draft.expiry_precision
        expiry_input = draft.expiry_input
        if precision_value not in {item.value for item in ExpiryPrecision}:
            if draft.expiry is not None:
                precision_value = ExpiryPrecision.EXACT_DATE.value
                expiry_input = draft.expiry.isoformat()
            elif (draft.selected_category or draft.category_suggestion) == "SHORT_TERM":
                precision_value = ExpiryPrecision.AUTO_NEAREST.value
                expiry_input = None
            else:
                return None
        return ExpiryRequest(
            expiry_input=expiry_input,
            precision=ExpiryPrecision(precision_value),
            ticker=draft.ticker,
            strike=draft.strike,
            option_side=draft.option_side,
        )

    async def _persist_expiry_resolution(
        self,
        draft_id: uuid.UUID,
        *,
        result: ExpiryResolution,
        expected_version: int,
        actor_user_id: int | None,
        interaction_id: int | None,
        action_type: str,
    ) -> ReviewDraft:
        async with self.database.session() as session:
            draft = await self._locked_draft(session, draft_id, expected_version)
            before = _audit_payload(draft)
            self._apply_resolution_to_draft(draft, result)
            draft.version += 1
            if actor_user_id is not None and interaction_id is not None:
                await self._add_audit(
                    session,
                    draft,
                    actor_user_id,
                    interaction_id,
                    action_type,
                    before,
                )
            await session.commit()
            return await self._snapshot(session, draft)

    @staticmethod
    def _apply_resolution_to_draft(draft: TradeDraft, result: ExpiryResolution) -> None:
        draft.expiry = result.resolved_expiry
        draft.expiry_input = result.expiry_input
        draft.expiry_precision = result.precision.value
        draft.expiry_resolution_status = result.resolution_status.value
        draft.option_contract_code = result.option_contract_code
        draft.contract_validation_status = result.validation_status.value
        payload = dict(draft.parse_payload)
        payload.update(
            {
                "expiry_input": result.expiry_input,
                "expiry_precision": result.precision.value,
                "resolved_expiry": (
                    result.resolved_expiry.isoformat() if result.resolved_expiry else None
                ),
                "expiry": result.resolved_expiry.isoformat() if result.resolved_expiry else None,
                "expiry_resolution_status": result.resolution_status.value,
                "contract_validation_status": result.validation_status.value,
                "option_contract_code": result.option_contract_code,
                "expiry_candidates": [candidate.isoformat() for candidate in result.candidates],
            }
        )
        draft.parse_payload = payload
        warnings = [
            warning
            for warning in draft.warnings
            if warning
            not in {
                "OPTION_CHAIN_UNAVAILABLE",
                "OPTION_CONTRACT_NOT_FOUND",
                "MULTIPLE_EXPIRATIONS_REQUIRE_MANAGER",
            }
        ]
        if result.warning:
            warnings.append(result.warning)
        draft.warnings = list(dict.fromkeys(warnings))
        missing = [field for field in draft.missing_fields if field not in {"expiry", "contract"}]
        if result.resolved_expiry is None:
            missing.append("expiry")
        draft.missing_fields = list(dict.fromkeys(missing))

    async def _locked_draft(
        self, session: AsyncSession, draft_id: uuid.UUID, expected_version: int
    ) -> TradeDraft:
        draft = await session.scalar(
            select(TradeDraft).where(TradeDraft.id == draft_id).with_for_update()
        )
        if draft is None:
            raise ReviewError("DRAFT_NOT_FOUND")
        self._assert_editable(draft)
        self._assert_version(draft, expected_version)
        return draft

    @staticmethod
    def _assert_editable(draft: TradeDraft) -> None:
        if draft.status not in ACTIVE_REVIEW_STATUSES:
            raise ReviewValidationError("DRAFT_NOT_EDITABLE")

    @staticmethod
    def _assert_version(draft: TradeDraft, expected_version: int) -> None:
        if draft.version != expected_version:
            raise ReviewConflictError("DRAFT_VERSION_CONFLICT")

    @staticmethod
    def _mark_edited(draft: TradeDraft, actor_user_id: int) -> None:
        draft.status = DraftStatus.PENDING_REVIEW.value
        draft.reviewed_by = actor_user_id
        draft.version += 1

    @staticmethod
    def _clear_short_term_fields(draft: TradeDraft) -> None:
        draft.intent = "NEW_TRADE"
        draft.action = "ENTRY"
        draft.action_stage = None
        draft.mentor_id = None
        draft.matched_trade_id = None
        draft.position_delta_eighths = None
        draft.position_after_eighths = None
        draft.avg_cost = None
        draft.sl = None
        draft.tp1 = None
        draft.tp2 = None
        draft.current_pnl_pct = None
        payload = dict(draft.parse_payload)
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
        draft.parse_payload = payload

    @staticmethod
    def _validate_edit(values: DraftEdit) -> None:
        if values.intent not in {"NEW_TRADE", "UPDATE_TRADE"}:
            raise ReviewValidationError("INTENT_INVALID")
        if values.action not in {
            "ENTRY",
            "ADD",
            "UPDATE",
            "TP1",
            "TP2",
            "RUNNER",
            "PARTIAL_SL",
            "SL",
            "CLOSE",
            "CANCEL",
            "ROLL",
        }:
            raise ReviewValidationError("ACTION_INVALID")
        if values.action_stage not in {None, "NONE", "FIRST", "SECOND", "THIRD", "FOURTH"}:
            raise ReviewValidationError("ACTION_STAGE_INVALID")
        if values.action != "ADD" and values.action_stage not in {None, "NONE"}:
            raise ReviewValidationError("ACTION_STAGE_INVALID")
        if values.selected_category not in {None, "SHORT_TERM", "SWING", "LEAPS"}:
            raise ReviewValidationError("CATEGORY_INVALID")
        if values.option_side not in {None, "CALL", "PUT"}:
            raise ReviewValidationError("OPTION_SIDE_INVALID")
        if values.expiry is not None and values.expiry < date.today():
            raise ReviewValidationError("EXPIRY_IN_PAST")
        if values.ticker is not None and (
            not 1 <= len(values.ticker) <= 12
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
                for character in values.ticker
            )
        ):
            raise ReviewValidationError("TICKER_INVALID")
        nonnegative = (
            values.strike,
            values.entry_low,
            values.entry_high,
            values.action_price,
            values.avg_cost,
            values.sl,
            values.tp1,
            values.tp2,
        )
        all_decimals = (*nonnegative, values.current_pnl_pct)
        if any(value is not None and not value.is_finite() for value in all_decimals):
            raise ReviewValidationError("NUMBER_INVALID")
        if any(value is not None and value < 0 for value in nonnegative):
            raise ReviewValidationError("PRICE_INVALID")
        if values.strike is not None and values.strike == 0:
            raise ReviewValidationError("STRIKE_INVALID")
        if (
            values.entry_low is not None
            and values.entry_high is not None
            and values.entry_low > values.entry_high
        ):
            raise ReviewValidationError("ENTRY_RANGE_INVALID")
        if values.position_delta_eighths is not None and not (
            -8 <= values.position_delta_eighths <= 8
        ):
            raise ReviewValidationError("POSITION_DELTA_INVALID")
        if values.position_after_eighths is not None and not (
            0 <= values.position_after_eighths <= 8
        ):
            raise ReviewValidationError("POSITION_AFTER_INVALID")
        if (
            values.intent == "NEW_TRADE"
            and values.action == "ENTRY"
            and values.position_delta_eighths is not None
            and values.position_after_eighths is not None
            and values.position_delta_eighths != values.position_after_eighths
        ):
            raise ReviewValidationError("ENTRY_POSITION_MISMATCH")
        if values.replace_plan:
            CardReviewService._validate_plan_fields(
                option_side=values.option_side,
                current_stock=values.current_stock,
                starter=values.starter,
                add_zone_low=values.add_zone_low,
                add_zone_high=values.add_zone_high,
                stock_sl=values.stock_sl,
                stock_pt1=values.stock_pt1,
                stock_pt2=values.stock_pt2,
                stock_pt3=values.stock_pt3,
                fib_0618=values.fib_0618,
            )
        if values.public_thesis is not None and len(values.public_thesis) > 600:
            raise ReviewValidationError("PUBLIC_THESIS_TOO_LONG")

    @staticmethod
    def _validate_plan_fields(
        *,
        option_side: str | None,
        current_stock: Decimal | None,
        starter: Decimal | None,
        add_zone_low: Decimal | None,
        add_zone_high: Decimal | None,
        stock_sl: Decimal | None,
        stock_pt1: Decimal | None,
        stock_pt2: Decimal | None,
        stock_pt3: Decimal | None,
        fib_0618: Decimal | None,
    ) -> None:
        plan_values = (
            current_stock,
            starter,
            add_zone_low,
            add_zone_high,
            stock_sl,
            stock_pt1,
            stock_pt2,
            stock_pt3,
            fib_0618,
        )
        if any(
            value is not None and (not value.is_finite() or value <= 0) for value in plan_values
        ):
            raise ReviewValidationError("PLAN_PRICE_INVALID")
        if add_zone_low is not None and add_zone_high is not None and add_zone_low > add_zone_high:
            raise ReviewValidationError("PLAN_ADD_ZONE_INVALID")
        reference = starter or current_stock
        targets = [value for value in (stock_pt1, stock_pt2, stock_pt3) if value is not None]
        if reference is not None and option_side == "CALL":
            if stock_sl is not None and stock_sl >= reference:
                raise ReviewValidationError("PLAN_SL_DIRECTION_INVALID")
            if any(
                current <= previous
                for previous, current in zip([reference, *targets], targets, strict=False)
            ):
                raise ReviewValidationError("PLAN_TARGET_ORDER_INVALID")
        if reference is not None and option_side == "PUT":
            if stock_sl is not None and stock_sl <= reference:
                raise ReviewValidationError("PLAN_SL_DIRECTION_INVALID")
            if any(
                current >= previous
                for previous, current in zip([reference, *targets], targets, strict=False)
            ):
                raise ReviewValidationError("PLAN_TARGET_ORDER_INVALID")

    @staticmethod
    def _validate_short_term_edit(values: ShortTermDraftEdit) -> None:
        if values.selected_category not in {"SHORT_TERM", "SWING", "LEAPS"}:
            raise ReviewValidationError("CATEGORY_INVALID")
        if values.option_side not in {"CALL", "PUT"}:
            raise ReviewValidationError("OPTION_SIDE_INVALID")
        _, precision = parse_expiry_input(values.expiry_input)
        if values.expiry_input and precision is None:
            raise ReviewValidationError("EXPIRY_INVALID")
        if values.selected_category == "SWING" and precision is None:
            raise ReviewValidationError("SWING_EXPIRY_REQUIRED")
        if not 1 <= len(values.ticker) <= 12 or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for character in values.ticker
        ):
            raise ReviewValidationError("TICKER_INVALID")
        for value in (values.strike, values.entry_price):
            if not value.is_finite() or value <= 0:
                raise ReviewValidationError("PRICE_INVALID")

    @staticmethod
    async def _validate_position_transition(session: AsyncSession, draft: TradeDraft) -> None:
        if draft.intent != "UPDATE_TRADE" or draft.matched_trade_id is None:
            return
        trade = await session.get(Trade, draft.matched_trade_id)
        if trade is None:
            raise ReviewValidationError("TRADE_UNAVAILABLE")
        after = draft.position_after_eighths
        if after is None:
            return
        if draft.action == "ADD" and after < trade.position_eighths:
            raise ReviewValidationError("ADD_POSITION_DECREASED")
        if draft.action in {"TP1", "TP2", "PARTIAL_SL"} and after > trade.position_eighths:
            raise ReviewValidationError("REDUCTION_POSITION_INCREASED")
        if draft.action in {"SL", "CLOSE", "CANCEL"} and after != 0:
            raise ReviewValidationError("CLOSED_POSITION_NOT_ZERO")
        expected_delta = after - trade.position_eighths
        if expected_delta != 0 and draft.action_price is None:
            raise ReviewValidationError("POSITION_CHANGE_PRICE_REQUIRED")
        if (
            draft.position_delta_eighths is not None
            and draft.position_delta_eighths != expected_delta
        ):
            raise ReviewValidationError("POSITION_TRANSITION_MISMATCH")

    @staticmethod
    async def _add_audit(
        session: AsyncSession,
        draft: TradeDraft,
        actor_user_id: int,
        interaction_id: int,
        action_type: str,
        before: dict[str, object],
    ) -> None:
        session.add(
            AuditLog(
                guild_id=draft.guild_id,
                actor_user_id=actor_user_id,
                action_type=action_type,
                entity_type="trade_draft",
                entity_id=str(draft.id),
                before_json=before,
                after_json=_audit_payload(draft),
                discord_interaction_id=interaction_id,
            )
        )

    @staticmethod
    async def _snapshot(session: AsyncSession, draft: TradeDraft) -> ReviewDraft:
        mentor_name = None
        if draft.mentor_id is not None:
            mentor_name = await session.scalar(
                select(Mentor.name).where(Mentor.id == draft.mentor_id)
            )
        matched_trade_code = None
        if draft.matched_trade_id is not None:
            matched_trade_code = await session.scalar(
                select(Trade.public_trade_id).where(Trade.id == draft.matched_trade_id)
            )
        return ReviewDraft(
            id=draft.id,
            guild_id=draft.guild_id,
            draft_code=draft.draft_code,
            status=draft.status,
            intent=draft.intent,
            action=draft.action,
            action_stage=draft.action_stage,
            category_suggestion=draft.category_suggestion,
            selected_category=draft.selected_category,
            ticker=draft.ticker,
            expiry=draft.expiry,
            expiry_input=draft.expiry_input,
            expiry_precision=draft.expiry_precision,
            expiry_resolution_status=draft.expiry_resolution_status,
            option_contract_code=draft.option_contract_code,
            contract_validation_status=draft.contract_validation_status,
            price_parse_confidence=draft.price_parse_confidence,
            expiry_candidates=_expiry_candidates(draft.parse_payload),
            expiry_metadata_legacy="expiry_precision" not in draft.parse_payload,
            strike=draft.strike,
            option_side=draft.option_side,
            entry_low=draft.entry_low,
            entry_high=draft.entry_high,
            action_price=draft.action_price,
            avg_cost=draft.avg_cost,
            sl=draft.sl,
            tp1=draft.tp1,
            tp2=draft.tp2,
            position_delta_eighths=draft.position_delta_eighths,
            position_after_eighths=draft.position_after_eighths,
            current_pnl_pct=draft.current_pnl_pct,
            mentor_hint=draft.mentor_hint,
            mentor_id=draft.mentor_id,
            mentor_name=mentor_name,
            matched_trade_id=draft.matched_trade_id,
            matched_trade_code=matched_trade_code,
            parser_confidence=draft.parser_confidence,
            missing_fields=tuple(draft.missing_fields),
            warnings=tuple(draft.warnings),
            internal_notes=draft.internal_notes,
            reviewed_by=draft.reviewed_by,
            review_channel_id=draft.review_channel_id,
            review_message_id=draft.review_message_id,
            version=draft.version,
            current_stock=_plan_decimal(draft.parse_payload, "plan_current_stock"),
            starter=_plan_decimal(draft.parse_payload, "plan_starter"),
            add_zone_low=_plan_decimal(draft.parse_payload, "plan_add_zone_low"),
            add_zone_high=_plan_decimal(draft.parse_payload, "plan_add_zone_high"),
            stock_sl=_plan_decimal(draft.parse_payload, "plan_stock_sl"),
            stock_pt1=_plan_decimal(draft.parse_payload, "plan_stock_pt1"),
            stock_pt2=_plan_decimal(draft.parse_payload, "plan_stock_pt2"),
            stock_pt3=_plan_decimal(draft.parse_payload, "plan_stock_pt3"),
            fib_0618=_plan_decimal(draft.parse_payload, "plan_fib_0618"),
            public_thesis=_public_thesis(draft.parse_payload),
            is_lotto=draft.is_lotto,
            swing_mode=(
                str(draft.parse_payload.get("_swing_mode"))
                if draft.parse_payload.get("_swing_mode")
                else None
            ),
            personal_follow_override=(
                draft.parse_payload.get("_personal_follow_override")
                if isinstance(draft.parse_payload.get("_personal_follow_override"), bool)
                else None
            ),
        )
