from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.models import (
    PersonalAccountSnapshot,
    PersonalDailySummary,
    PersonalExecutionEvent,
    PersonalExecutionSetting,
    PersonalFill,
    PersonalOrder,
    PersonalPosition,
    PersonalPositionRiskEpoch,
    SourceMessage,
    Trade,
    TradeDraft,
    TradePublication,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import TradeCategory
from app.domain.personal_execution import (
    PersonalBrokerEnvironment,
    PersonalExecutionMode,
    PersonalExecutionPolicy,
    PersonalFollowScope,
    PersonalOrderPurpose,
    PersonalOrderStatus,
    PersonalPositionSource,
    PersonalPositionStatus,
    PersonalRiskStage,
    evaluate_risk,
    return_pct,
)
from app.integrations.moomoo_market_data import moomoo_option_code
from app.integrations.moomoo_personal_execution import (
    BrokerAccount,
    BrokerPosition,
    PersonalBroker,
    PersonalBrokerError,
)

ET = ZoneInfo("America/New_York")
ACTIVE_POSITION_STATUSES = {
    PersonalPositionStatus.PENDING_ENTRY.value,
    PersonalPositionStatus.PARTIALLY_FILLED.value,
    PersonalPositionStatus.ACTIVE.value,
    PersonalPositionStatus.BREAKEVEN_PROTECTED.value,
    PersonalPositionStatus.TRAILING.value,
    PersonalPositionStatus.RUNNER.value,
    PersonalPositionStatus.PAUSED.value,
}
ACTIVE_ORDER_STATUSES = {
    PersonalOrderStatus.PENDING.value,
    PersonalOrderStatus.SUBMITTED.value,
    PersonalOrderStatus.PARTIALLY_FILLED.value,
}
MOOMOO_OPTION_RE = re.compile(
    r"^US\.(?P<symbol>.+?)(?P<expiry>\d{6})(?P<side>[CP])(?P<strike>\d+)$"
)


class PersonalExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    code: str
    order_id: uuid.UUID | None = None
    broker_order_id: str | None = None
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class PersonalExecutionStatus:
    connected: bool
    execution_mode: str
    broker_environment: str
    auto_follow_enabled: bool
    follow_scope: str
    manual_position_sync_enabled: bool
    auto_risk_management_enabled: bool
    pause_new_entries: bool
    pause_auto_management: bool
    account_equity: Decimal | None
    buying_power: Decimal | None
    active_positions: int
    active_orders: int
    last_reconciled_at: datetime | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PositionView:
    id: uuid.UUID
    contract_code: str
    quantity: int
    average_cost: Decimal | None
    current_price: Decimal | None
    return_pct: Decimal | None
    status: str
    source: str
    risk_stage: str


@dataclass(frozen=True, slots=True)
class OrderView:
    id: uuid.UUID
    contract_code: str
    side: str
    quantity: int
    purpose: str
    limit_price: Decimal
    status: str
    created_at: datetime


def _hash_key(*parts: object) -> str:
    encoded = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_contract(code: str) -> tuple[str, date, Decimal, str]:
    match = MOOMOO_OPTION_RE.fullmatch(code.strip().upper())
    if match is None:
        raise PersonalExecutionError("MOOMOO_OPTION_CODE_INVALID")
    try:
        expiry = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    except ValueError as exc:
        raise PersonalExecutionError("MOOMOO_OPTION_EXPIRY_INVALID") from exc
    symbol = match.group("symbol").removeprefix(".")
    strike = Decimal(match.group("strike")) / Decimal("1000")
    side = "CALL" if match.group("side") == "C" else "PUT"
    return symbol, expiry, strike, side


class PersonalExecutionService:
    """Owner-only personal execution coordinator; public signals never depend on it."""

    def __init__(
        self,
        database: Database,
        broker: PersonalBroker,
        *,
        guild_id: int,
        owner_user_id: int,
        execution_mode: PersonalExecutionMode,
        broker_environment: PersonalBrokerEnvironment,
        policy: PersonalExecutionPolicy,
        production_start_date: date,
    ) -> None:
        self.database = database
        self.broker = broker
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self.execution_mode = execution_mode
        self.broker_environment = broker_environment
        self.policy = policy
        self.production_start_date = production_start_date

    async def ensure_settings(self) -> PersonalExecutionSetting:
        async with self.database.session() as session:
            setting = await session.get(PersonalExecutionSetting, self.guild_id)
            if setting is None:
                setting = PersonalExecutionSetting(
                    guild_id=self.guild_id,
                    execution_mode=self.execution_mode.value,
                    broker_environment=self.broker_environment.value,
                    auto_follow_enabled=False,
                    follow_scope=PersonalFollowScope.OWNER_ONLY.value,
                    manual_position_sync_enabled=False,
                    auto_risk_management_enabled=False,
                    pause_new_entries=False,
                    pause_auto_management=False,
                    entry_max_chase_pct=self.policy.entry_max_chase_pct,
                    position_equity_pct=self.policy.position_equity_pct,
                    position_budget_min=self.policy.position_budget_min,
                    position_budget_max=self.policy.position_budget_max,
                    trailing_stop_pct=self.policy.trailing_stop_pct,
                    max_quote_age_seconds=self.policy.max_quote_age_seconds,
                    max_bid_ask_spread_pct=self.policy.max_bid_ask_spread_pct,
                    minimum_option_volume=self.policy.minimum_option_volume,
                    minimum_open_interest=self.policy.minimum_open_interest,
                    short_term_entry_ttl_minutes=self.policy.short_term_entry_ttl_minutes,
                    swing_entry_ttl_minutes=self.policy.swing_entry_ttl_minutes,
                    market_open_guard_enabled=self.policy.market_open_guard_enabled,
                    market_open_guard_minutes=self.policy.market_open_guard_minutes,
                )
                session.add(setting)
            else:
                # Environment and safety policy come from deployment configuration.
                setting.execution_mode = self.execution_mode.value
                setting.broker_environment = self.broker_environment.value
            await session.commit()
            return setting

    async def update_toggle(self, name: str, *, actor_user_id: int) -> None:
        allowed = {
            "auto_follow_enabled",
            "manual_position_sync_enabled",
            "auto_risk_management_enabled",
            "pause_new_entries",
            "pause_auto_management",
        }
        if name not in allowed:
            raise PersonalExecutionError("TOGGLE_INVALID")
        if actor_user_id != self.owner_user_id:
            raise PersonalExecutionError("OWNER_ONLY")
        async with self.database.session() as session:
            setting = await session.get(PersonalExecutionSetting, self.guild_id)
            if setting is None:
                raise PersonalExecutionError("PERSONAL_SETTINGS_MISSING")
            new_value = not bool(getattr(setting, name))
            setattr(setting, name, new_value)
            setting.updated_by = actor_user_id
            await self._event(
                session,
                event_key=_hash_key("toggle", self.guild_id, name, setting.updated_at, new_value),
                event_type="CONTROL_TOGGLE_CHANGED",
                payload={"control": name, "enabled": new_value},
            )
            await session.commit()

    async def cycle_follow_scope(self, *, actor_user_id: int) -> None:
        if actor_user_id != self.owner_user_id:
            raise PersonalExecutionError("OWNER_ONLY")
        async with self.database.session() as session:
            setting = await session.get(PersonalExecutionSetting, self.guild_id)
            if setting is None:
                raise PersonalExecutionError("PERSONAL_SETTINGS_MISSING")
            setting.follow_scope = (
                PersonalFollowScope.ALL_ELIGIBLE_SIGNALS.value
                if setting.follow_scope == PersonalFollowScope.OWNER_ONLY.value
                else PersonalFollowScope.OWNER_ONLY.value
            )
            setting.updated_by = actor_user_id
            await self._event(
                session,
                event_key=_hash_key(
                    "scope",
                    self.guild_id,
                    setting.updated_at,
                    setting.follow_scope,
                ),
                event_type="FOLLOW_SCOPE_CHANGED",
                payload={"follow_scope": setting.follow_scope},
            )
            await session.commit()

    async def prepare_publication(
        self,
        publication_id: uuid.UUID,
        *,
        published_entry: Decimal | None,
        actor_user_id: int | None,
        force_follow: bool | None = None,
    ) -> ExecutionOutcome:
        setting = await self.ensure_settings()
        if force_follow is False:
            return await self._record_skip(publication_id, "SIGNAL_OVERRIDE_SKIP")
        if not setting.auto_follow_enabled and force_follow is not True:
            return ExecutionOutcome("AUTO_FOLLOW_DISABLED")
        if setting.pause_new_entries:
            return ExecutionOutcome("NEW_ENTRIES_PAUSED")

        async with self.database.session() as session:
            row = (
                await session.execute(
                    select(TradePublication, TradeDraft, Trade, SourceMessage)
                    .join(TradeDraft, TradeDraft.id == TradePublication.draft_id)
                    .join(Trade, Trade.id == TradePublication.trade_id)
                    .join(SourceMessage, SourceMessage.id == TradeDraft.source_message_id)
                    .where(TradePublication.id == publication_id)
                )
            ).one_or_none()
            if row is None:
                raise PersonalExecutionError("PUBLICATION_CONTEXT_MISSING")
            publication, draft, trade, source = row
            if source.received_at.astimezone(ET).date() < self.production_start_date:
                return await self._skip(session, publication_id, "PRE_PRODUCTION_SIGNAL")
            if setting.follow_scope == PersonalFollowScope.OWNER_ONLY.value and (
                source.submitted_by != self.owner_user_id
                or (actor_user_id or draft.reviewed_by) != self.owner_user_id
            ):
                return await self._skip(session, publication_id, "OWNER_SCOPE_MISMATCH")
            if trade.category not in {
                TradeCategory.SHORT_TERM.value,
                TradeCategory.SWING.value,
            }:
                return await self._skip(session, publication_id, "CATEGORY_NOT_ELIGIBLE")
            if draft.action == "CLOSE" and trade.category == TradeCategory.SWING.value:
                return await self._prepare_swing_close(session, publication, trade)
            if draft.action != "ENTRY" or draft.intent != "NEW_TRADE":
                return await self._skip(session, publication_id, "ACTION_NOT_ENTRY")
            if published_entry is None or published_entry <= 0:
                return await self._skip(session, publication_id, "ENTRY_PRICE_MISSING")
            contract_code = self._contract_code(trade)

        account = await self.broker.read_account()
        quote = await self.broker.read_quote(contract_code)
        broker_positions = await self.broker.read_positions()
        if any(
            item.contract_code == contract_code and item.quantity > 0
            for item in broker_positions
        ):
            return await self._record_skip(publication_id, "DUPLICATE_BROKER_CONTRACT")
        now = utc_now()
        quote_age = now - (
            quote.observed_at if quote.observed_at.tzinfo else quote.observed_at.replace(tzinfo=UTC)
        )
        if quote_age > timedelta(seconds=self.policy.max_quote_age_seconds):
            return await self._record_skip(publication_id, "QUOTE_STALE")
        if quote.spread_pct > self.policy.max_bid_ask_spread_pct:
            return await self._record_skip(publication_id, "SPREAD_TOO_WIDE")
        if (
            self.policy.minimum_option_volume is not None
            and (quote.volume is None or quote.volume < self.policy.minimum_option_volume)
        ):
            return await self._record_skip(publication_id, "OPTION_VOLUME_TOO_LOW")
        if (
            self.policy.minimum_open_interest is not None
            and (
                quote.open_interest is None
                or quote.open_interest < self.policy.minimum_open_interest
            )
        ):
            return await self._record_skip(publication_id, "OPEN_INTEREST_TOO_LOW")
        if account.equity is None or account.buying_power is None:
            return await self._record_skip(publication_id, "ACCOUNT_BUDGET_UNAVAILABLE")

        limit_price = min(quote.ask, self.policy.max_entry_price(published_entry))
        if quote.ask > self.policy.max_entry_price(published_entry):
            return await self._record_skip(publication_id, "MAX_CHASE_EXCEEDED")
        budget = self.policy.effective_budget(account.equity, account.buying_power)
        quantity = self.policy.entry_quantity(budget, limit_price)
        if quantity <= 0:
            return await self._record_skip(publication_id, "BUDGET_BELOW_ONE_CONTRACT")

        async with self.database.session() as session:
            duplicate = await session.scalar(
                select(PersonalPosition.id).where(
                    PersonalPosition.guild_id == self.guild_id,
                    PersonalPosition.account_ref == account.account_ref,
                    PersonalPosition.broker_contract_code == contract_code,
                    PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                )
            )
            if duplicate is not None:
                return await self._skip(session, publication_id, "DUPLICATE_CONTRACT_POSITION")
            key = _hash_key("entry", publication_id, account.account_ref, self.execution_mode.value)
            existing = await session.scalar(
                select(PersonalOrder).where(PersonalOrder.idempotency_key == key)
            )
            if existing is not None:
                return ExecutionOutcome(
                    "IDEMPOTENT_REUSE",
                    existing.id,
                    existing.broker_order_id,
                    self.execution_mode is PersonalExecutionMode.DRY_RUN,
                )
            publication = await session.get(TradePublication, publication_id)
            if publication is None or publication.trade_id is None:
                raise PersonalExecutionError("PUBLICATION_CONTEXT_MISSING")
            trade = await session.get(Trade, publication.trade_id)
            if trade is None:
                raise PersonalExecutionError("TRADE_NOT_FOUND")
            order = PersonalOrder(
                guild_id=self.guild_id,
                linked_trade_id=trade.id,
                linked_publication_id=publication.id,
                account_ref=account.account_ref,
                contract_key=contract_code,
                broker_contract_code=contract_code,
                purpose=PersonalOrderPurpose.ENTRY.value,
                side="BUY",
                order_type="LIMIT",
                execution_mode=self.execution_mode.value,
                broker_environment=self.broker_environment.value,
                idempotency_key=key,
                quantity=quantity,
                limit_price=limit_price,
                status=(
                    PersonalOrderStatus.DRY_RUN_VALIDATED.value
                    if self.execution_mode is PersonalExecutionMode.DRY_RUN
                    else PersonalOrderStatus.PENDING.value
                ),
                filled_quantity=0,
                expires_at=now
                + timedelta(minutes=self.policy.entry_ttl_minutes(trade.category)),
                axis_owned=True,
            )
            session.add(order)
            await session.flush()
            await self._event(
                session,
                event_key=f"personal-order-created:{key}",
                event_type=(
                    "DRY_RUN_ENTRY_VALIDATED"
                    if self.execution_mode is PersonalExecutionMode.DRY_RUN
                    else "ENTRY_PENDING_BROKER_ACK"
                ),
                payload={
                    "order_id": str(order.id),
                    "contract": contract_code,
                    "quantity": quantity,
                    "limit_price": str(limit_price),
                    "budget": str(budget),
                },
                order_id=order.id,
            )
            await self._snapshot(session, account, "ENTRY_DECISION")
            await session.commit()
            order_id = order.id

        if self.execution_mode is PersonalExecutionMode.DRY_RUN:
            return ExecutionOutcome("DRY_RUN_VALIDATED", order_id)
        try:
            ack = await self.broker.place_limit_order(
                contract_code=contract_code,
                side="BUY",
                quantity=quantity,
                limit_price=limit_price,
                purpose=PersonalOrderPurpose.ENTRY.value,
                idempotency_key=key,
            )
        except PersonalBrokerError as exc:
            await self._mark_order_failed(order_id, exc.code)
            raise PersonalExecutionError(exc.code) from exc
        async with self.database.session() as session:
            order = await session.get(PersonalOrder, order_id)
            if order is None:
                raise PersonalExecutionError("PERSONAL_ORDER_MISSING")
            order.broker_order_id = ack.broker_order_id
            order.status = PersonalOrderStatus.SUBMITTED.value
            order.submitted_at = ack.submitted_at
            await session.commit()
        return ExecutionOutcome("BROKER_ACKNOWLEDGED", order_id, ack.broker_order_id, False)

    async def reconcile(self) -> None:
        setting = await self.ensure_settings()
        await self._expire_axis_orders()
        account = await self.broker.read_account()
        positions = await self.broker.read_positions()
        orders = await self.broker.read_orders()
        fills = await self.broker.read_fills()
        now = utc_now()
        async with self.database.session() as session:
            setting = await session.get(PersonalExecutionSetting, self.guild_id)
            if setting is None:
                raise PersonalExecutionError("PERSONAL_SETTINGS_MISSING")
            setting.account_ref = account.account_ref
            setting.last_reconciled_at = now
            await self._snapshot(session, account, "RECONCILIATION")
            known_positions = {
                item.broker_contract_code: item
                for item in (
                    await session.scalars(
                        select(PersonalPosition).where(
                            PersonalPosition.guild_id == self.guild_id,
                            PersonalPosition.account_ref == account.account_ref,
                            PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                        )
                    )
                ).all()
            }
            broker_positions = {item.contract_code: item for item in positions if item.quantity > 0}
            await self._sync_orders(session, account.account_ref, orders, now)
            for contract_code, broker_position in broker_positions.items():
                personal = known_positions.get(contract_code)
                entry_order = None
                if personal is None:
                    entry_order = await session.scalar(
                        select(PersonalOrder).where(
                            PersonalOrder.guild_id == self.guild_id,
                            PersonalOrder.account_ref == account.account_ref,
                            PersonalOrder.broker_contract_code == contract_code,
                            PersonalOrder.purpose == PersonalOrderPurpose.ENTRY.value,
                            PersonalOrder.broker_order_id.is_not(None),
                        ).order_by(PersonalOrder.created_at.desc())
                    )
                    if entry_order is not None:
                        personal = self._new_axis_position(
                            account,
                            broker_position,
                            entry_order,
                            now,
                        )
                    elif setting.manual_position_sync_enabled:
                        try:
                            personal = self._new_manual_position(account, broker_position, now)
                        except PersonalExecutionError:
                            await self._event(
                                session,
                                event_key=_hash_key(
                                    "unsupported-position",
                                    account.account_ref,
                                    contract_code,
                                ),
                                event_type="BROKER_POSITION_IGNORED",
                                payload={"reason": "NON_OPTION_OR_UNSUPPORTED_CONTRACT"},
                            )
                            continue
                    else:
                        continue
                    session.add(personal)
                    await session.flush()
                    if entry_order is not None:
                        entry_order.personal_position_id = personal.id
                    await self._start_epoch(session, personal, now)
                    await self._event(
                        session,
                        event_key=_hash_key(
                            "position-import",
                            personal.id,
                            personal.source,
                        ),
                        event_type="BROKER_POSITION_IMPORTED",
                        payload={
                            "position_id": str(personal.id),
                            "contract": contract_code,
                            "quantity": personal.quantity,
                            "source": personal.source,
                        },
                        position_id=personal.id,
                    )
                    known_positions[contract_code] = personal
                else:
                    await self._sync_position(session, personal, broker_position, now)
            for contract_code, personal in known_positions.items():
                if contract_code not in broker_positions and personal.quantity > 0:
                    personal.quantity = 0
                    personal.status = PersonalPositionStatus.CLOSED_MANUAL.value
                    personal.closed_at = now
                    personal.last_broker_sync_at = now
                    await self._event(
                        session,
                        event_key=_hash_key("manual-close", personal.id, now),
                        event_type="BROKER_POSITION_CLOSED",
                        payload={"position_id": str(personal.id), "source": "BROKER"},
                        position_id=personal.id,
                    )
            await self._sync_fills(session, account, fills)
            await session.commit()
        if setting.auto_risk_management_enabled and not setting.pause_auto_management:
            await self.evaluate_positions()

    async def evaluate_positions(self) -> None:
        async with self.database.session() as session:
            setting = await session.get(PersonalExecutionSetting, self.guild_id)
            if setting is None or not setting.account_ref:
                return
            positions = (
                await session.scalars(
                    select(PersonalPosition).where(
                        PersonalPosition.guild_id == self.guild_id,
                        PersonalPosition.account_ref == setting.account_ref,
                        PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                        PersonalPosition.quantity > 0,
                    )
                )
            ).all()
            position_ids = [item.id for item in positions]
        for position_id in position_ids:
            await self._evaluate_position(position_id)

    async def status(self) -> PersonalExecutionStatus:
        setting = await self.ensure_settings()
        error_code = None
        account = None
        try:
            account = await self.broker.read_account()
        except PersonalBrokerError as exc:
            error_code = exc.code
        async with self.database.session() as session:
            active_positions = len(
                (
                    await session.scalars(
                        select(PersonalPosition.id).where(
                            PersonalPosition.guild_id == self.guild_id,
                            PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                        )
                    )
                ).all()
            )
            active_orders = len(
                (
                    await session.scalars(
                        select(PersonalOrder.id).where(
                            PersonalOrder.guild_id == self.guild_id,
                            PersonalOrder.status.in_(ACTIVE_ORDER_STATUSES),
                        )
                    )
                ).all()
            )
        return PersonalExecutionStatus(
            connected=account is not None,
            execution_mode=setting.execution_mode,
            broker_environment=setting.broker_environment,
            auto_follow_enabled=setting.auto_follow_enabled,
            follow_scope=setting.follow_scope,
            manual_position_sync_enabled=setting.manual_position_sync_enabled,
            auto_risk_management_enabled=setting.auto_risk_management_enabled,
            pause_new_entries=setting.pause_new_entries,
            pause_auto_management=setting.pause_auto_management,
            account_equity=account.equity if account else None,
            buying_power=account.buying_power if account else None,
            active_positions=active_positions,
            active_orders=active_orders,
            last_reconciled_at=setting.last_reconciled_at,
            error_code=error_code,
        )

    async def positions(self) -> tuple[PositionView, ...]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(PersonalPosition)
                    .where(PersonalPosition.guild_id == self.guild_id)
                    .order_by(PersonalPosition.updated_at.desc())
                    .limit(25)
                )
            ).all()
            return tuple(
                PositionView(
                    item.id,
                    item.broker_contract_code,
                    item.quantity,
                    item.average_cost,
                    item.current_price,
                    item.current_return_pct,
                    item.status,
                    item.source,
                    item.risk_stage,
                )
                for item in rows
            )

    async def orders(self) -> tuple[OrderView, ...]:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(PersonalOrder)
                    .where(PersonalOrder.guild_id == self.guild_id)
                    .order_by(PersonalOrder.created_at.desc())
                    .limit(25)
                )
            ).all()
            return tuple(
                OrderView(
                    item.id,
                    item.broker_contract_code,
                    item.side,
                    item.quantity,
                    item.purpose,
                    item.limit_price,
                    item.status,
                    item.created_at,
                )
                for item in rows
            )

    async def pending_events(self) -> tuple[PersonalExecutionEvent, ...]:
        async with self.database.session() as session:
            return tuple(
                (
                    await session.scalars(
                        select(PersonalExecutionEvent)
                        .where(
                            PersonalExecutionEvent.guild_id == self.guild_id,
                            PersonalExecutionEvent.notified_at.is_(None),
                        )
                        .order_by(PersonalExecutionEvent.created_at)
                        .limit(50)
                    )
                ).all()
            )

    async def daily_summary(
        self,
        session_date: date,
    ) -> tuple[uuid.UUID, dict[str, Any], bool]:
        async with self.database.session() as session:
            existing = await session.scalar(
                select(PersonalDailySummary).where(
                    PersonalDailySummary.guild_id == self.guild_id,
                    PersonalDailySummary.session_date == session_date,
                )
            )
            if existing is not None:
                return existing.id, existing.snapshot_json, existing.status == "PUBLISHED"
            fills = (
                await session.scalars(
                    select(PersonalFill).where(
                        PersonalFill.guild_id == self.guild_id,
                        PersonalFill.executed_at
                        >= datetime.combine(session_date, datetime.min.time(), tzinfo=ET),
                        PersonalFill.executed_at
                        < datetime.combine(
                            session_date + timedelta(days=1),
                            datetime.min.time(),
                            tzinfo=ET,
                        ),
                    )
                )
            ).all()
            positions = (
                await session.scalars(
                    select(PersonalPosition).where(
                        PersonalPosition.guild_id == self.guild_id,
                        PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                    )
                )
            ).all()
            realized = sum((item.realized_pnl or Decimal("0") for item in fills), Decimal("0"))
            snapshot: dict[str, Any] = {
                "session_date": session_date.isoformat(),
                "fills": len(fills),
                "active_positions": len(positions),
                "realized_pnl": str(realized),
                "execution_mode": self.execution_mode.value,
            }
            summary = PersonalDailySummary(
                guild_id=self.guild_id,
                session_date=session_date,
                snapshot_json=snapshot,
                status="PENDING",
            )
            session.add(summary)
            await session.flush()
            await session.commit()
            return summary.id, snapshot, False

    async def mark_daily_summary_published(
        self,
        summary_id: uuid.UUID,
        message_id: int,
    ) -> None:
        async with self.database.session() as session:
            summary = await session.get(PersonalDailySummary, summary_id)
            if summary is not None:
                summary.status = "PUBLISHED"
                summary.discord_message_id = message_id
                summary.published_at = utc_now()
                await session.commit()

    async def mark_event_notified(self, event_id: uuid.UUID) -> None:
        async with self.database.session() as session:
            event = await session.get(PersonalExecutionEvent, event_id)
            if event is not None:
                event.notified_at = utc_now()
                await session.commit()

    async def _evaluate_position(self, position_id: uuid.UUID) -> None:
        async with self.database.session() as session:
            position = await session.get(PersonalPosition, position_id)
            if position is None or position.average_cost is None or position.quantity <= 0:
                return
            contract_code = position.broker_contract_code
        quote = await self.broker.read_quote(contract_code)
        async with self.database.session() as session:
            position = await session.get(PersonalPosition, position_id)
            if position is None or position.average_cost is None or position.quantity <= 0:
                return
            prior_high = position.risk_high_watermark or position.average_cost
            decision = evaluate_risk(
                policy=self.policy,
                average_cost=position.average_cost,
                current_price=quote.bid,
                current_quantity=position.quantity,
                original_quantity=position.original_managed_quantity,
                prior_stage=PersonalRiskStage(position.risk_stage),
                prior_risk_high=prior_high,
                tp50_executed=position.tp50_executed,
                tp100_executed=position.tp100_executed,
                observed_at=quote.observed_at,
            )
            position.current_price = quote.bid
            position.current_return_pct = decision.return_pct
            position.lifetime_high_price = max(
                position.lifetime_high_price or quote.bid,
                quote.bid,
            )
            # 09:30-09:35 does not update the epoch high. At guard exit, reset to live bid.
            if decision.opening_guard:
                position.opening_guard_last_active = True
            else:
                position.risk_high_watermark = (
                    quote.bid if position.opening_guard_last_active else decision.risk_high
                )
                position.opening_guard_last_active = False
            position.risk_stage = decision.stage.value
            position.protection_reference = decision.protection
            position.last_quote_at = quote.observed_at
            position.status = {
                PersonalRiskStage.INITIAL: PersonalPositionStatus.ACTIVE.value,
                PersonalRiskStage.BREAKEVEN: PersonalPositionStatus.BREAKEVEN_PROTECTED.value,
                PersonalRiskStage.TRAILING: PersonalPositionStatus.TRAILING.value,
                PersonalRiskStage.RUNNER: PersonalPositionStatus.RUNNER.value,
                PersonalRiskStage.PAUSED: PersonalPositionStatus.PAUSED.value,
            }[decision.stage]
            if decision.order_purpose is None or decision.sell_quantity <= 0:
                await session.commit()
                return
            key = _hash_key(
                "risk",
                position.id,
                position.risk_epoch_number,
                decision.order_purpose.value,
            )
            existing = await session.scalar(
                select(PersonalOrder.id).where(PersonalOrder.idempotency_key == key)
            )
            if existing is not None:
                await session.commit()
                return
            order = PersonalOrder(
                guild_id=self.guild_id,
                personal_position_id=position.id,
                linked_trade_id=position.linked_trade_id,
                linked_publication_id=position.linked_publication_id,
                account_ref=position.account_ref,
                contract_key=position.contract_key,
                broker_contract_code=position.broker_contract_code,
                purpose=decision.order_purpose.value,
                side="SELL",
                order_type="LIMIT",
                execution_mode=self.execution_mode.value,
                broker_environment=self.broker_environment.value,
                idempotency_key=key,
                quantity=decision.sell_quantity,
                limit_price=quote.bid.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
                status=(
                    PersonalOrderStatus.DRY_RUN_VALIDATED.value
                    if self.execution_mode is PersonalExecutionMode.DRY_RUN
                    else PersonalOrderStatus.PENDING.value
                ),
                filled_quantity=0,
                axis_owned=True,
            )
            session.add(order)
            await session.flush()
            await self._event(
                session,
                event_key=f"risk-order:{key}",
                event_type=f"{decision.order_purpose.value}_TRIGGERED",
                payload={
                    "position_id": str(position.id),
                    "quantity": decision.sell_quantity,
                    "reference": str(decision.protection),
                    "dry_run": self.execution_mode is PersonalExecutionMode.DRY_RUN,
                },
                position_id=position.id,
                order_id=order.id,
            )
            await session.commit()
            order_id = order.id
            limit_price = order.limit_price
            purpose = order.purpose
            quantity = order.quantity
        if self.execution_mode is PersonalExecutionMode.LIVE:
            try:
                ack = await self.broker.place_limit_order(
                    contract_code=contract_code,
                    side="SELL",
                    quantity=quantity,
                    limit_price=limit_price,
                    purpose=purpose,
                    idempotency_key=key,
                )
            except PersonalBrokerError as exc:
                await self._mark_order_failed(order_id, exc.code)
                raise
            async with self.database.session() as session:
                order = await session.get(PersonalOrder, order_id)
                if order is not None:
                    order.broker_order_id = ack.broker_order_id
                    order.status = PersonalOrderStatus.SUBMITTED.value
                    order.submitted_at = ack.submitted_at
                    await session.commit()

    async def _prepare_swing_close(
        self,
        session: Any,
        publication: TradePublication,
        trade: Trade,
    ) -> ExecutionOutcome:
        positions = (
            await session.scalars(
                select(PersonalPosition).where(
                    PersonalPosition.guild_id == self.guild_id,
                    PersonalPosition.linked_trade_id == trade.id,
                    PersonalPosition.status.in_(ACTIVE_POSITION_STATUSES),
                    PersonalPosition.quantity > 0,
                )
            )
        ).all()
        if len(positions) != 1:
            return await self._skip(session, publication.id, "SWING_CLOSE_POSITION_AMBIGUOUS")
        position = positions[0]
        if position.current_price is None:
            return await self._skip(session, publication.id, "SWING_CLOSE_PRICE_MISSING")
        key = _hash_key("swing-close", publication.id, position.id, self.execution_mode.value)
        existing = await session.scalar(
            select(PersonalOrder).where(PersonalOrder.idempotency_key == key)
        )
        if existing is not None:
            return ExecutionOutcome("IDEMPOTENT_REUSE", existing.id, existing.broker_order_id)
        order = PersonalOrder(
            guild_id=self.guild_id,
            personal_position_id=position.id,
            linked_trade_id=trade.id,
            linked_publication_id=publication.id,
            account_ref=position.account_ref,
            contract_key=position.contract_key,
            broker_contract_code=position.broker_contract_code,
            purpose=PersonalOrderPurpose.SWING_CLOSE_EXIT.value,
            side="SELL",
            order_type="LIMIT",
            execution_mode=self.execution_mode.value,
            broker_environment=self.broker_environment.value,
            idempotency_key=key,
            quantity=position.quantity,
            limit_price=position.current_price,
            status=(
                PersonalOrderStatus.DRY_RUN_VALIDATED.value
                if self.execution_mode is PersonalExecutionMode.DRY_RUN
                else PersonalOrderStatus.PENDING.value
            ),
            filled_quantity=0,
            axis_owned=True,
        )
        session.add(order)
        await session.flush()
        await self._event(
            session,
            event_key=f"swing-close:{key}",
            event_type="SWING_CLOSE_ORDER_CREATED",
            payload={"position_id": str(position.id), "quantity": position.quantity},
            position_id=position.id,
            order_id=order.id,
        )
        await session.commit()
        order_id = order.id
        if self.execution_mode is PersonalExecutionMode.DRY_RUN:
            return ExecutionOutcome("DRY_RUN_VALIDATED", order_id)
        try:
            ack = await self.broker.place_limit_order(
                contract_code=position.broker_contract_code,
                side="SELL",
                quantity=position.quantity,
                limit_price=position.current_price,
                purpose=PersonalOrderPurpose.SWING_CLOSE_EXIT.value,
                idempotency_key=key,
            )
        except PersonalBrokerError as exc:
            await self._mark_order_failed(order_id, exc.code)
            raise PersonalExecutionError(exc.code) from exc
        async with self.database.session() as update_session:
            saved = await update_session.get(PersonalOrder, order_id)
            if saved is None:
                raise PersonalExecutionError("PERSONAL_ORDER_MISSING")
            saved.broker_order_id = ack.broker_order_id
            saved.status = PersonalOrderStatus.SUBMITTED.value
            saved.submitted_at = ack.submitted_at
            await update_session.commit()
        return ExecutionOutcome("BROKER_ACKNOWLEDGED", order_id, ack.broker_order_id, False)

    async def _sync_position(
        self,
        session: Any,
        personal: PersonalPosition,
        broker_position: BrokerPosition,
        now: datetime,
    ) -> None:
        if broker_position.quantity > personal.quantity:
            previous_quantity = personal.quantity
            personal.source = PersonalPositionSource.AXIS_AUTO_MANUAL_ADD.value
            current_epoch = await session.scalar(
                select(PersonalPositionRiskEpoch).where(
                    PersonalPositionRiskEpoch.personal_position_id == personal.id,
                    PersonalPositionRiskEpoch.epoch_number == personal.risk_epoch_number,
                )
            )
            if current_epoch is not None:
                current_epoch.ended_at = now
            personal.risk_epoch_number += 1
            personal.quantity = broker_position.quantity
            personal.average_cost = broker_position.average_cost
            personal.risk_high_watermark = broker_position.average_cost
            personal.risk_stage = PersonalRiskStage.INITIAL.value
            personal.protection_reference = broker_position.average_cost * Decimal("0.70")
            await self._start_epoch(session, personal, now, quantity=broker_position.quantity)
            await self._event(
                session,
                event_key=_hash_key(
                    "broker-add",
                    personal.id,
                    personal.risk_epoch_number,
                    broker_position.quantity,
                ),
                event_type="BROKER_POSITION_ADDED",
                payload={
                    "position_id": str(personal.id),
                    "previous_quantity": previous_quantity,
                    "quantity": broker_position.quantity,
                    "risk_epoch": personal.risk_epoch_number,
                },
                position_id=personal.id,
            )
        elif broker_position.quantity < personal.quantity:
            await self._event(
                session,
                event_key=_hash_key(
                    "broker-partial",
                    personal.id,
                    personal.quantity,
                    broker_position.quantity,
                ),
                event_type="BROKER_POSITION_PARTIALLY_CLOSED",
                payload={
                    "position_id": str(personal.id),
                    "previous_quantity": personal.quantity,
                    "quantity": broker_position.quantity,
                },
                position_id=personal.id,
            )
        personal.quantity = broker_position.quantity
        personal.original_managed_quantity = max(
            personal.original_managed_quantity,
            broker_position.quantity,
        )
        personal.average_cost = broker_position.average_cost
        personal.total_cost_basis = broker_position.average_cost * broker_position.quantity * 100
        personal.current_price = broker_position.current_price
        if broker_position.current_price is not None:
            personal.current_return_pct = return_pct(
                broker_position.average_cost,
                broker_position.current_price,
            )
            personal.lifetime_high_price = max(
                personal.lifetime_high_price or broker_position.current_price,
                broker_position.current_price,
            )
        personal.last_broker_sync_at = now
        personal.version += 1

    def _new_axis_position(
        self,
        account: BrokerAccount,
        broker_position: BrokerPosition,
        order: PersonalOrder,
        now: datetime,
    ) -> PersonalPosition:
        position = self._new_manual_position(account, broker_position, now)
        position.source = PersonalPositionSource.AXIS_AUTO.value
        position.linked_trade_id = order.linked_trade_id
        position.linked_publication_id = order.linked_publication_id
        return position

    def _new_manual_position(
        self,
        account: BrokerAccount,
        broker_position: BrokerPosition,
        now: datetime,
    ) -> PersonalPosition:
        symbol, expiry, strike, side = _parse_contract(broker_position.contract_code)
        current_return = (
            return_pct(broker_position.average_cost, broker_position.current_price)
            if broker_position.current_price is not None
            else None
        )
        return PersonalPosition(
            guild_id=self.guild_id,
            account_ref=account.account_ref,
            contract_key=broker_position.contract_code,
            broker_contract_code=broker_position.contract_code,
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            option_side=side,
            source=PersonalPositionSource.MANUAL_MOOMOO.value,
            status=PersonalPositionStatus.ACTIVE.value,
            quantity=broker_position.quantity,
            original_managed_quantity=broker_position.quantity,
            average_cost=broker_position.average_cost,
            total_cost_basis=broker_position.average_cost * broker_position.quantity * 100,
            current_price=broker_position.current_price,
            current_return_pct=current_return,
            lifetime_high_price=broker_position.current_price or broker_position.average_cost,
            risk_high_watermark=broker_position.average_cost,
            risk_stage=PersonalRiskStage.INITIAL.value,
            protection_reference=broker_position.average_cost * Decimal("0.70"),
            risk_epoch_number=1,
            opened_at=now,
            last_broker_sync_at=now,
        )

    async def _start_epoch(
        self,
        session: Any,
        position: PersonalPosition,
        now: datetime,
        *,
        quantity: int | None = None,
    ) -> None:
        session.add(
            PersonalPositionRiskEpoch(
                personal_position_id=position.id,
                epoch_number=position.risk_epoch_number,
                started_at=now,
                starting_quantity=quantity if quantity is not None else position.quantity,
                average_cost=position.average_cost or Decimal("0"),
                risk_high_watermark=position.risk_high_watermark or Decimal("0"),
                risk_stage=position.risk_stage,
                protection_reference=position.protection_reference,
            )
        )

    async def _sync_orders(
        self,
        session: Any,
        account_ref: str,
        broker_orders: tuple[Any, ...],
        now: datetime,
    ) -> None:
        for broker_order in broker_orders:
            order = await session.scalar(
                select(PersonalOrder).where(
                    PersonalOrder.account_ref == account_ref,
                    PersonalOrder.broker_order_id == broker_order.broker_order_id,
                )
            )
            if order is None:
                continue
            order.status = broker_order.status
            order.filled_quantity = broker_order.filled_quantity
            order.average_fill_price = broker_order.average_fill_price
            order.last_broker_sync_at = now
            if broker_order.status in {
                PersonalOrderStatus.FILLED.value,
                PersonalOrderStatus.CANCELLED.value,
                PersonalOrderStatus.REJECTED.value,
            }:
                order.terminal_at = now
            if (
                order.personal_position_id is not None
                and broker_order.status == PersonalOrderStatus.FILLED.value
            ):
                position = await session.get(PersonalPosition, order.personal_position_id)
                if position is not None:
                    if order.purpose == PersonalOrderPurpose.TP50.value:
                        position.tp50_executed = True
                    elif order.purpose == PersonalOrderPurpose.TP100.value:
                        position.tp100_executed = True

    async def _expire_axis_orders(self) -> None:
        now = utc_now()
        async with self.database.session() as session:
            orders = (
                await session.scalars(
                    select(PersonalOrder).where(
                        PersonalOrder.guild_id == self.guild_id,
                        PersonalOrder.axis_owned.is_(True),
                        PersonalOrder.status.in_(ACTIVE_ORDER_STATUSES),
                        PersonalOrder.expires_at.is_not(None),
                        PersonalOrder.expires_at <= now,
                    )
                )
            ).all()
            targets = [(item.id, item.broker_order_id) for item in orders]
        for order_id, broker_order_id in targets:
            if (
                self.execution_mode is PersonalExecutionMode.LIVE
                and broker_order_id is not None
            ):
                try:
                    await self.broker.cancel_order(broker_order_id)
                except PersonalBrokerError as exc:
                    await self._mark_order_failed(order_id, exc.code)
                    continue
            async with self.database.session() as session:
                order = await session.get(PersonalOrder, order_id)
                if order is not None and order.status in ACTIVE_ORDER_STATUSES:
                    order.status = PersonalOrderStatus.EXPIRED.value
                    order.terminal_at = now
                    await session.commit()

    async def _sync_fills(
        self,
        session: Any,
        account: BrokerAccount,
        broker_fills: tuple[Any, ...],
    ) -> None:
        for fill in broker_fills:
            existing = await session.scalar(
                select(PersonalFill.id).where(
                    PersonalFill.account_ref == account.account_ref,
                    PersonalFill.broker_fill_id == fill.broker_fill_id,
                )
            )
            if existing is not None:
                continue
            order = None
            if fill.broker_order_id:
                order = await session.scalar(
                    select(PersonalOrder).where(
                        PersonalOrder.account_ref == account.account_ref,
                        PersonalOrder.broker_order_id == fill.broker_order_id,
                    )
                )
            position = (
                await session.get(PersonalPosition, order.personal_position_id)
                if order is not None and order.personal_position_id is not None
                else None
            )
            session.add(
                PersonalFill(
                    guild_id=self.guild_id,
                    personal_position_id=order.personal_position_id if order else None,
                    personal_order_id=order.id if order else None,
                    account_ref=account.account_ref,
                    broker_fill_id=fill.broker_fill_id,
                    contract_key=fill.contract_code,
                    side=fill.side,
                    quantity=fill.quantity,
                    fill_price=fill.fill_price,
                    cash_amount=fill.fill_price * fill.quantity * 100,
                    realized_pnl=(
                        (fill.fill_price - position.average_cost) * fill.quantity * 100
                        if fill.side == "SELL"
                        and position is not None
                        and position.average_cost is not None
                        else None
                    ),
                    realized_return_pct=(
                        return_pct(position.average_cost, fill.fill_price)
                        if fill.side == "SELL"
                        and position is not None
                        and position.average_cost is not None
                        else None
                    ),
                    remaining_quantity=position.quantity if position is not None else None,
                    account_equity=account.equity,
                    execution_source="AXIS" if order else "BROKER_MANUAL",
                    executed_at=fill.executed_at,
                )
            )

    def _contract_code(self, trade: Trade) -> str:
        if trade.moomoo_option_code:
            return trade.moomoo_option_code
        if trade.option_contract_code:
            try:
                return moomoo_option_code(trade.option_contract_code)
            except Exception as exc:
                raise PersonalExecutionError("OPTION_CONTRACT_INVALID") from exc
        raise PersonalExecutionError("OPTION_CONTRACT_MISSING")

    async def _record_skip(self, publication_id: uuid.UUID, code: str) -> ExecutionOutcome:
        async with self.database.session() as session:
            return await self._skip(session, publication_id, code)

    async def _skip(
        self,
        session: Any,
        publication_id: uuid.UUID,
        code: str,
    ) -> ExecutionOutcome:
        await self._event(
            session,
            event_key=_hash_key("publication-skip", publication_id, code),
            event_type="AUTO_ENTRY_SKIPPED",
            payload={"publication_id": str(publication_id), "reason": code},
        )
        await session.commit()
        return ExecutionOutcome(code)

    async def _mark_order_failed(self, order_id: uuid.UUID, error_code: str) -> None:
        async with self.database.session() as session:
            order = await session.get(PersonalOrder, order_id)
            if order is not None:
                order.status = PersonalOrderStatus.FAILED.value
                order.last_error_code = error_code[:100]
                order.terminal_at = utc_now()
                await session.commit()

    async def _event(
        self,
        session: Any,
        *,
        event_key: str,
        event_type: str,
        payload: dict[str, Any],
        position_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
    ) -> None:
        existing = await session.scalar(
            select(PersonalExecutionEvent.id).where(
                PersonalExecutionEvent.event_key == event_key[:160]
            )
        )
        if existing is None:
            session.add(
                PersonalExecutionEvent(
                    guild_id=self.guild_id,
                    personal_position_id=position_id,
                    personal_order_id=order_id,
                    event_key=event_key[:160],
                    event_type=event_type,
                    payload=payload,
                )
            )

    async def _snapshot(
        self,
        session: Any,
        account: BrokerAccount,
        event_type: str,
    ) -> None:
        session.add(
            PersonalAccountSnapshot(
                guild_id=self.guild_id,
                account_ref=account.account_ref,
                event_type=event_type,
                account_equity=account.equity,
                available_buying_power=account.buying_power,
                cash=account.cash,
                captured_at=account.observed_at,
            )
        )
