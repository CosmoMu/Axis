from __future__ import annotations

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
ORDER_NOTIFICATION_STATUSES = {"SUBMITTED", "CANCELLED", "REJECTED"}


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
                notify = initialized and order.status in ORDER_NOTIFICATION_STATUSES
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
                            notification_pending=notify,
                        )
                    )
                    continue
                changed = current.state_signature != signature
                current.instrument_code = order.instrument_code
                current.side = order.side
                current.quantity = order.quantity
                current.filled_quantity = order.filled_quantity
                current.limit_price = order.limit_price
                current.average_fill_price = order.average_fill_price
                current.status = order.status
                current.state_signature = signature
                current.broker_updated_at = order.updated_at
                if changed and notify:
                    current.notification_pending = True
                    current.notified_at = None

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
            fills = tuple(
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
            remaining = max(0, limit - len(fills))
            orders = tuple(
                (
                    await session.scalars(
                        select(MoomooActivityOrder)
                        .where(
                            MoomooActivityOrder.guild_id == self.guild_id,
                            MoomooActivityOrder.notification_pending.is_(True),
                        )
                        .order_by(MoomooActivityOrder.updated_at.asc())
                        .limit(remaining)
                    )
                ).all()
            )
            events = [
                MoomooActivityEvent(
                    kind="FILL",
                    record_id=item.id,
                    account_label=_account_label(item.account_ref),
                    instrument_code=item.instrument_code,
                    side=item.side,
                    quantity=item.quantity,
                    price=item.fill_price,
                    status=None,
                    occurred_at=item.executed_at,
                )
                for item in fills
            ]
            events.extend(
                MoomooActivityEvent(
                    kind="ORDER",
                    record_id=item.id,
                    account_label=_account_label(item.account_ref),
                    instrument_code=item.instrument_code,
                    side=item.side,
                    quantity=item.quantity,
                    price=item.limit_price,
                    status=item.status,
                    occurred_at=item.broker_updated_at,
                )
                for item in orders
            )
            return tuple(
                sorted(
                    events,
                    key=lambda item: item.occurred_at
                    or datetime.min.replace(tzinfo=UTC),
                )
            )

    async def mark_notified(self, event: MoomooActivityEvent) -> None:
        async with self.database.session() as session:
            if event.kind == "FILL":
                row = await session.get(MoomooActivityFill, event.record_id)
                if row is not None:
                    row.notified_at = utc_now()
            else:
                row = await session.get(MoomooActivityOrder, event.record_id)
                if row is not None:
                    row.notification_pending = False
                    row.notified_at = utc_now()
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
                "accounts": latest.get("accounts", []),
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
