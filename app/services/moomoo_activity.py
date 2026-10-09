from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.models import (
    MoomooActivityDailySummary,
    MoomooActivityFill,
    MoomooActivityOrder,
    MoomooActivityState,
    utc_now,
)
from app.db.session import Database
from app.integrations.moomoo_activity import ActivitySnapshot, MoomooActivityReader

ET = ZoneInfo("America/New_York")
OPTION_CODE = re.compile(r"^(?:US\.)?[A-Z]+\d{6}[CP]\d+$")


@dataclass(frozen=True, slots=True)
class MoomooActivityEvent:
    kind: str
    record_id: uuid.UUID
    account_label: str
    instrument_code: str
    side: str
    quantity: Decimal
    price: Decimal | None
    status: str | None
    occurred_at: datetime | None
    record_ids: tuple[uuid.UUID, ...] = ()
    action: str = "BUY"
    entry_price: Decimal | None = None
    return_percent: Decimal | None = None
    profit_amount: Decimal | None = None
    position_fraction: Decimal | None = None
    total_return_percent: Decimal | None = None
    total_profit_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MoomooDailySummaryClaim:
    id: uuid.UUID
    session_date: date
    snapshot: dict[str, Any]


def _account_label(account_ref: str) -> str:
    return f"账户 …{account_ref[-4:]}"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.01")))


def _number(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _looks_like_option(code: str) -> bool:
    return OPTION_CODE.fullmatch(code.strip().upper()) is not None


def _order_signature(order: Any) -> str:
    return "|".join(
        (
            order.status,
            _number(order.quantity),
            _number(order.filled_quantity),
            _number(order.limit_price) if order.limit_price is not None else "",
            _number(order.average_fill_price) if order.average_fill_price is not None else "",
        )
    )


def _group_fills(
    fills: tuple[MoomooActivityFill, ...],
) -> tuple[dict[str, Any], ...]:
    """Combine executions belonging to one broker order into one activity event."""

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for fill in fills:
        broker_key = fill.broker_order_id or f"fill:{fill.broker_fill_id}"
        key = (
            fill.account_ref,
            broker_key,
            fill.instrument_code,
            fill.side,
        )
        group = grouped.setdefault(
            key,
            {
                "record_ids": [],
                "account_ref": fill.account_ref,
                "instrument_code": fill.instrument_code,
                "side": fill.side,
                "quantity": Decimal("0"),
                "notional": Decimal("0"),
                "executed_at": fill.executed_at,
            },
        )
        group["record_ids"].append(fill.id)
        group["quantity"] += fill.quantity
        group["notional"] += fill.quantity * fill.fill_price
        group["executed_at"] = max(group["executed_at"], fill.executed_at)
    output = []
    for group in grouped.values():
        quantity = group["quantity"]
        group["fill_price"] = group["notional"] / quantity
        group["record_ids"] = tuple(group["record_ids"])
        output.append(group)
    return tuple(sorted(output, key=lambda item: item["executed_at"]))


class MoomooActivityService:
    def __init__(
        self,
        database: Database,
        reader: MoomooActivityReader,
        *,
        guild_id: int,
    ) -> None:
        self.database = database
        self.reader = reader
        self.guild_id = guild_id

    async def reconcile(self) -> ActivitySnapshot:
        snapshot = await self.reader.read_snapshot()
        now = utc_now()
        async with self.database.session() as session:
            state = await session.get(MoomooActivityState, self.guild_id)
            if state is None:
                state = MoomooActivityState(guild_id=self.guild_id, latest_snapshot={})
                session.add(state)
                await session.flush()
            initialized = state.initialized_at is not None

            for order in snapshot.orders:
                current = await session.scalar(
                    select(MoomooActivityOrder).where(
                        MoomooActivityOrder.guild_id == self.guild_id,
                        MoomooActivityOrder.account_ref == order.account_ref,
                        MoomooActivityOrder.broker_order_id == order.broker_order_id,
                    )
                )
                signature = _order_signature(order)
                if current is None:
                    session.add(
                        MoomooActivityOrder(
                            guild_id=self.guild_id,
                            account_ref=order.account_ref,
                            broker_order_id=order.broker_order_id,
                            instrument_code=order.instrument_code,
                            side=order.side,
                            quantity=order.quantity,
                            filled_quantity=order.filled_quantity,
                            limit_price=order.limit_price,
                            average_fill_price=order.average_fill_price,
                            status=order.status,
                            state_signature=signature,
                            broker_updated_at=order.updated_at,
                            notification_pending=False,
                            notified_at=now,
                        )
                    )
                    continue
                current.instrument_code = order.instrument_code
                current.side = order.side
                current.quantity = order.quantity
                current.filled_quantity = order.filled_quantity
                current.limit_price = order.limit_price
                current.average_fill_price = order.average_fill_price
                current.status = order.status
                current.state_signature = signature
                current.broker_updated_at = order.updated_at
                current.notification_pending = False
                current.notified_at = current.notified_at or now

            for fill in snapshot.fills:
                current = await session.scalar(
                    select(MoomooActivityFill).where(
                        MoomooActivityFill.guild_id == self.guild_id,
                        MoomooActivityFill.account_ref == fill.account_ref,
                        MoomooActivityFill.broker_fill_id == fill.broker_fill_id,
                    )
                )
                if current is not None:
                    continue
                session.add(
                    MoomooActivityFill(
                        guild_id=self.guild_id,
                        account_ref=fill.account_ref,
                        broker_fill_id=fill.broker_fill_id,
                        broker_order_id=fill.broker_order_id,
                        instrument_code=fill.instrument_code,
                        side=fill.side,
                        quantity=fill.quantity,
                        fill_price=fill.fill_price,
                        executed_at=fill.executed_at,
                        notified_at=None if initialized else now,
                    )
                )

            state.initialized_at = state.initialized_at or now
            state.last_reconciled_at = now
            state.latest_snapshot = self._serialize_snapshot(snapshot)
            await session.commit()
        return snapshot

    async def pending_events(self, *, limit: int = 50) -> tuple[MoomooActivityEvent, ...]:
        async with self.database.session() as session:
            pending = tuple(
                (
                    await session.scalars(
                        select(MoomooActivityFill)
                        .where(
                            MoomooActivityFill.guild_id == self.guild_id,
                            MoomooActivityFill.notified_at.is_(None),
                        )
                        .order_by(MoomooActivityFill.executed_at.asc())
                        .limit(limit)
                    )
                ).all()
            )
            if not pending:
                return ()
            all_fills = tuple(
                (
                    await session.scalars(
                        select(MoomooActivityFill)
                        .where(
                            MoomooActivityFill.guild_id == self.guild_id,
                        )
                        .order_by(
                            MoomooActivityFill.executed_at.asc(),
                            MoomooActivityFill.created_at.asc(),
                        )
                    )
                ).all()
            )
            pending_ids = {item.id for item in pending}
            events: list[MoomooActivityEvent] = []
            ledgers: dict[tuple[str, str], dict[str, Decimal]] = {}
            for item in _group_fills(all_fills):
                key = (item["account_ref"], item["instrument_code"])
                ledger = ledgers.setdefault(
                    key,
                    {
                        "quantity": Decimal("0"),
                        "cost": Decimal("0"),
                        "invested": Decimal("0"),
                        "realized": Decimal("0"),
                    },
                )
                is_buy = item["side"].upper().startswith("BUY")
                entry_price = (
                    ledger["cost"] / ledger["quantity"]
                    if ledger["quantity"] > 0
                    else None
                )
                action = "BUY"
                return_percent = None
                profit_amount = None
                position_fraction = None
                total_return_percent = None
                total_profit_amount = None
                if is_buy:
                    ledger["quantity"] += item["quantity"]
                    ledger["cost"] += item["quantity"] * item["fill_price"]
                    ledger["invested"] += item["quantity"] * item["fill_price"]
                else:
                    action = "SELL"
                    before_quantity = ledger["quantity"]
                    multiplier = (
                        Decimal("100")
                        if _looks_like_option(item["instrument_code"])
                        else Decimal("1")
                    )
                    if entry_price is not None:
                        return_percent = (
                            (item["fill_price"] - entry_price) / entry_price * Decimal("100")
                        )
                        profit_amount = (
                            (item["fill_price"] - entry_price)
                            * item["quantity"]
                            * multiplier
                        )
                        ledger["realized"] += profit_amount
                    if before_quantity > 0:
                        position_fraction = min(
                            Decimal("1"), item["quantity"] / before_quantity
                        )
                        sold = min(item["quantity"], before_quantity)
                        ledger["quantity"] = before_quantity - sold
                        if entry_price is not None:
                            ledger["cost"] = ledger["quantity"] * entry_price
                    if before_quantity > 0 and ledger["quantity"] <= 0:
                        action = "CLOSE"
                        total_profit_amount = ledger["realized"]
                        total_return_percent = (
                            ledger["realized"] / (ledger["invested"] * multiplier) * Decimal("100")
                            if ledger["invested"] > 0
                            else None
                        )
                        ledger["quantity"] = Decimal("0")
                        ledger["cost"] = Decimal("0")
                        ledger["invested"] = Decimal("0")
                        ledger["realized"] = Decimal("0")
                if pending_ids.isdisjoint(item["record_ids"]):
                    continue
                events.append(
                    MoomooActivityEvent(
                        kind="FILL",
                        record_id=item["record_ids"][0],
                        record_ids=item["record_ids"],
                        account_label=_account_label(item["account_ref"]),
                        instrument_code=item["instrument_code"],
                        side=item["side"],
                        quantity=item["quantity"],
                        price=item["fill_price"],
                        status=None,
                        occurred_at=item["executed_at"],
                        action=action,
                        entry_price=entry_price,
                        return_percent=return_percent,
                        profit_amount=profit_amount,
                        position_fraction=position_fraction,
                        total_return_percent=total_return_percent,
                        total_profit_amount=total_profit_amount,
                    )
                )
            return tuple(events)

    async def mark_notified(self, event: MoomooActivityEvent) -> None:
        async with self.database.session() as session:
            if event.kind == "FILL":
                record_ids = event.record_ids or (event.record_id,)
                rows = list(
                    await session.scalars(
                        select(MoomooActivityFill).where(
                            MoomooActivityFill.id.in_(record_ids)
                        )
                    )
                )
                notified_at = utc_now()
                for row in rows:
                    row.notified_at = notified_at
            await session.commit()

    async def prepare_daily_summary(self, session_date: date) -> MoomooDailySummaryClaim | None:
        await self.reconcile()
        start_et = datetime.combine(session_date, time.min, tzinfo=ET)
        end_et = start_et + timedelta(days=1)
        async with self.database.session() as session:
            existing = await session.scalar(
                select(MoomooActivityDailySummary).where(
                    MoomooActivityDailySummary.guild_id == self.guild_id,
                    MoomooActivityDailySummary.session_date == session_date,
                )
            )
            if existing is not None and existing.published_at is not None:
                return None
            fills = tuple(
                (
                    await session.scalars(
                        select(MoomooActivityFill)
                        .where(
                            MoomooActivityFill.guild_id == self.guild_id,
                            MoomooActivityFill.executed_at >= start_et.astimezone(UTC),
                            MoomooActivityFill.executed_at < end_et.astimezone(UTC),
                        )
                        .order_by(MoomooActivityFill.executed_at.asc())
                    )
                ).all()
            )
            state = await session.get(MoomooActivityState, self.guild_id)
            latest = dict(state.latest_snapshot if state is not None else {})
            previous = await session.scalar(
                select(MoomooActivityDailySummary)
                .where(
                    MoomooActivityDailySummary.guild_id == self.guild_id,
                    MoomooActivityDailySummary.session_date < session_date,
                )
                .order_by(MoomooActivityDailySummary.session_date.desc())
                .limit(1)
            )
            previous_equity = {
                str(item.get("account")): Decimal(str(item["equity"]))
                for item in (previous.snapshot_json.get("accounts", []) if previous else [])
                if item.get("account") and item.get("equity") is not None
            }
            accounts = []
            for item in latest.get("accounts", []):
                current = dict(item)
                prior = previous_equity.get(str(current.get("account")))
                equity = current.get("equity")
                if prior not in (None, Decimal("0")) and equity is not None:
                    current["equity_change_percent"] = _number(
                        (Decimal(str(equity)) - prior) / prior * Decimal("100")
                    )
                accounts.append(current)
            payload = {
                "session_date": session_date.isoformat(),
                "fills": [
                    {
                        "account": _account_label(item.account_ref),
                        "code": item.instrument_code,
                        "side": item.side,
                        "quantity": _number(item.quantity),
                        "price": _number(item.fill_price),
                        "time": item.executed_at.astimezone(ET).strftime("%H:%M ET"),
                    }
                    for item in fills
                ],
                "accounts": accounts,
                "positions": latest.get("positions", []),
            }
            if existing is None:
                existing = MoomooActivityDailySummary(
                    guild_id=self.guild_id,
                    session_date=session_date,
                    snapshot_json=payload,
                    discord_message_ids=[],
                )
                session.add(existing)
                await session.flush()
            else:
                existing.snapshot_json = payload
            await session.commit()
            return MoomooDailySummaryClaim(existing.id, session_date, payload)

    async def mark_summary_published(
        self, summary_id: uuid.UUID, message_ids: list[int]
    ) -> None:
        async with self.database.session() as session:
            summary = await session.get(MoomooActivityDailySummary, summary_id)
            if summary is None:
                return
            summary.discord_message_ids = message_ids
            summary.published_at = utc_now()
            await session.commit()

    @staticmethod
    def _serialize_snapshot(snapshot: ActivitySnapshot) -> dict[str, Any]:
        return {
            "observed_at": snapshot.observed_at.isoformat(),
            "accounts": [
                {
                    "account": _account_label(item.account_ref),
                    "equity": _money(item.equity),
                    "buying_power": _money(item.buying_power),
                    "cash": _money(item.cash),
                }
                for item in snapshot.accounts
            ],
            "positions": [
                {
                    "account": _account_label(item.account_ref),
                    "code": item.instrument_code,
                    "quantity": _number(item.quantity),
                    "average_cost": _money(item.average_cost),
                    "current_price": _money(item.current_price),
                    "unrealized_pnl": _money(item.unrealized_pnl),
                }
                for item in snapshot.positions
            ],
        }
