from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
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
OPTION_PARTS = re.compile(r"^(?:US\.)?([A-Z]+)(\d{6})([CP])(\d+)$")


@dataclass(frozen=True, slots=True)
class MoomooActivityStrategyLeg:
    instrument_code: str
    side: str
    quantity: Decimal
    price: Decimal


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
    position_quantity: Decimal | None = None
    position_average_cost: Decimal | None = None
    strategy_type: str | None = None
    strategy_display: str | None = None
    strategy_price_kind: str | None = None
    strategy_legs: tuple[MoomooActivityStrategyLeg, ...] = ()


@dataclass(frozen=True, slots=True)
class MoomooDailySummaryClaim:
    id: uuid.UUID
    session_date: date
    snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MoomooFeeSchedule:
    """Configurable Moomoo Canada public fee schedule, denominated in USD."""

    option_commission_per_contract: Decimal = Decimal("0.65")
    option_commission_minimum: Decimal = Decimal("1.00")
    stock_commission_per_share: Decimal = Decimal("0.0049")
    stock_commission_minimum: Decimal = Decimal("0.99")
    stock_platform_fee_per_share: Decimal = Decimal("0.005")
    stock_platform_fee_minimum: Decimal = Decimal("1.00")
    low_price_stock_rate: Decimal = Decimal("0.0005")
    sec_fee_rate: Decimal = Decimal("0.0000206")
    sec_fee_minimum: Decimal = Decimal("0.01")


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
                "broker_order_id": broker_key,
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


def _parse_option_contract(code: str) -> tuple[str, str, str, Decimal] | None:
    match = OPTION_PARTS.fullmatch(code.strip().upper())
    if match is None:
        return None
    ticker, expiry, option_type, strike_raw = match.groups()
    return ticker, expiry, option_type, Decimal(strike_raw) / Decimal("1000")


def _strike_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _combine_butterfly_order(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Recognize a three-leg 1:-2:1 option butterfly from one broker order."""

    if len(items) != 3:
        return None
    parsed = [_parse_option_contract(str(item["instrument_code"])) for item in items]
    if any(item is None for item in parsed):
        return None
    contracts = [item for item in parsed if item is not None]
    ticker, expiry, option_type, _ = contracts[0]
    if any(item[:3] != (ticker, expiry, option_type) for item in contracts):
        return None
    ordered = sorted(zip(items, contracts, strict=True), key=lambda item: item[1][3])
    low, middle, high = ordered
    if middle[1][3] - low[1][3] != high[1][3] - middle[1][3]:
        return None
    wing_quantity = Decimal(str(low[0]["quantity"]))
    if (
        wing_quantity <= 0
        or Decimal(str(high[0]["quantity"])) != wing_quantity
        or Decimal(str(middle[0]["quantity"])) != wing_quantity * Decimal("2")
    ):
        return None

    low_buy = str(low[0]["side"]).upper().startswith("BUY")
    middle_buy = str(middle[0]["side"]).upper().startswith("BUY")
    high_buy = str(high[0]["side"]).upper().startswith("BUY")
    if low_buy and not middle_buy and high_buy:
        side = "BUY"
    elif not low_buy and middle_buy and not high_buy:
        side = "SELL"
    else:
        return None

    buy_notional = sum(
        Decimal(str(item["quantity"])) * Decimal(str(item["fill_price"]))
        for item, _ in ordered
        if str(item["side"]).upper().startswith("BUY")
    )
    sell_notional = sum(
        Decimal(str(item["quantity"])) * Decimal(str(item["fill_price"]))
        for item, _ in ordered
        if str(item["side"]).upper().startswith("SELL")
    )
    net_debit = buy_notional - sell_notional
    price_kind = "DEBIT" if net_debit >= 0 else "CREDIT"
    strategy_price = abs(net_debit) / wing_quantity
    strikes = "/".join(_strike_text(item[1][3]) for item in ordered)
    display = f"{ticker} {expiry[2:4]}/{expiry[4:6]} {strikes}{option_type}"
    canonical_code = f"US.{ticker}{expiry}{option_type}{strikes}"
    record_ids = tuple(record_id for item, _ in ordered for record_id in item["record_ids"])
    return {
        "record_ids": record_ids,
        "account_ref": low[0]["account_ref"],
        "broker_order_id": low[0]["broker_order_id"],
        "instrument_code": canonical_code,
        "side": side,
        "quantity": wing_quantity,
        "fill_price": strategy_price,
        "executed_at": max(item[0]["executed_at"] for item in ordered),
        "strategy_type": "BUTTERFLY",
        "strategy_display": display,
        "strategy_price_kind": price_kind,
        "strategy_legs": tuple(
            MoomooActivityStrategyLeg(
                instrument_code=str(item[0]["instrument_code"]),
                side=str(item[0]["side"]),
                quantity=Decimal(str(item[0]["quantity"])),
                price=Decimal(str(item[0]["fill_price"])),
            )
            for item in ordered
        ),
    }


def _group_activity_fills(
    fills: tuple[MoomooActivityFill, ...],
) -> tuple[dict[str, Any], ...]:
    """Group split executions and merge recognized multi-leg strategy orders."""

    grouped = _group_fills(fills)
    by_order: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in grouped:
        key = (str(item["account_ref"]), str(item["broker_order_id"]))
        by_order.setdefault(key, []).append(item)
    output: list[dict[str, Any]] = []
    for items in by_order.values():
        butterfly = _combine_butterfly_order(items)
        if butterfly is not None:
            output.append(butterfly)
        else:
            output.extend(items)
    return tuple(sorted(output, key=lambda item: item["executed_at"]))


def _round_fee(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _group_fee(group: dict[str, Any], schedule: MoomooFeeSchedule) -> Decimal:
    quantity = Decimal(str(group["quantity"]))
    price = Decimal(str(group["fill_price"]))
    is_option = _looks_like_option(str(group["instrument_code"]))
    if is_option:
        fee = max(
            schedule.option_commission_minimum,
            schedule.option_commission_per_contract * quantity,
        )
        notional = price * quantity * Decimal("100")
    else:
        rate = (
            schedule.stock_commission_per_share
            if price >= Decimal("1")
            else schedule.low_price_stock_rate
        )
        platform_rate = (
            schedule.stock_platform_fee_per_share
            if price >= Decimal("1")
            else schedule.low_price_stock_rate
        )
        fee = max(schedule.stock_commission_minimum, rate * quantity)
        fee += max(schedule.stock_platform_fee_minimum, platform_rate * quantity)
        notional = price * quantity
    if str(group["side"]).upper().startswith("SELL"):
        fee += max(schedule.sec_fee_minimum, schedule.sec_fee_rate * notional)
    return _round_fee(fee)


def _closed_trade_returns(
    fills: tuple[MoomooActivityFill, ...],
) -> tuple[tuple[datetime, Decimal], ...]:
    """Return completed long-position cycle returns, keyed by final close time."""

    ledgers: dict[tuple[str, str], dict[str, Decimal]] = {}
    completed: list[tuple[datetime, Decimal]] = []
    for item in _group_activity_fills(fills):
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
        quantity = Decimal(str(item["quantity"]))
        price = Decimal(str(item["fill_price"]))
        if str(item["side"]).upper().startswith("BUY"):
            ledger["quantity"] += quantity
            ledger["cost"] += quantity * price
            ledger["invested"] += quantity * price
            continue
        before_quantity = ledger["quantity"]
        if before_quantity <= 0:
            continue
        entry_price = ledger["cost"] / before_quantity
        multiplier = (
            Decimal("100")
            if (item.get("strategy_type") or _looks_like_option(str(item["instrument_code"])))
            else Decimal("1")
        )
        sold = min(quantity, before_quantity)
        ledger["realized"] += (price - entry_price) * sold * multiplier
        ledger["quantity"] = before_quantity - sold
        ledger["cost"] = ledger["quantity"] * entry_price
        if ledger["quantity"] > 0:
            continue
        if ledger["invested"] > 0:
            completed.append(
                (
                    item["executed_at"],
                    ledger["realized"] / (ledger["invested"] * multiplier) * Decimal("100"),
                )
            )
        ledger["quantity"] = Decimal("0")
        ledger["cost"] = Decimal("0")
        ledger["invested"] = Decimal("0")
        ledger["realized"] = Decimal("0")
    return tuple(completed)


class MoomooActivityService:
    def __init__(
        self,
        database: Database,
        reader: MoomooActivityReader,
        *,
        guild_id: int,
        fee_schedule: MoomooFeeSchedule | None = None,
    ) -> None:
        self.database = database
        self.reader = reader
        self.guild_id = guild_id
        self.fee_schedule = fee_schedule or MoomooFeeSchedule()

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

            serialized = self._serialize_snapshot(snapshot)
            observed_et = snapshot.observed_at.astimezone(ET)
            prior_snapshot = dict(state.latest_snapshot or {})
            open_date = prior_snapshot.get("daily_open_date")
            open_accounts = prior_snapshot.get("daily_open_accounts")
            if (
                observed_et.time() >= time(9, 29)
                and observed_et.time() < time(16, 15)
                and open_date != observed_et.date().isoformat()
            ):
                open_date = observed_et.date().isoformat()
                open_accounts = serialized["accounts"]
            if open_date and open_accounts:
                serialized["daily_open_date"] = open_date
                serialized["daily_open_accounts"] = open_accounts
            state.initialized_at = state.initialized_at or now
            state.last_reconciled_at = now
            state.latest_snapshot = serialized
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
            for item in _group_activity_fills(all_fills):
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
                    ledger["cost"] / ledger["quantity"] if ledger["quantity"] > 0 else None
                )
                action = "BUY"
                return_percent = None
                profit_amount = None
                position_fraction = None
                total_return_percent = None
                total_profit_amount = None
                position_quantity = None
                position_average_cost = None
                if is_buy:
                    before_quantity = ledger["quantity"]
                    ledger["quantity"] += item["quantity"]
                    ledger["cost"] += item["quantity"] * item["fill_price"]
                    ledger["invested"] += item["quantity"] * item["fill_price"]
                    position_quantity = ledger["quantity"]
                    position_average_cost = ledger["cost"] / ledger["quantity"]
                    if before_quantity > 0:
                        action = "ADD"
                else:
                    action = "SELL"
                    before_quantity = ledger["quantity"]
                    multiplier = (
                        Decimal("100")
                        if (
                            item.get("strategy_type") or _looks_like_option(item["instrument_code"])
                        )
                        else Decimal("1")
                    )
                    if entry_price is not None:
                        return_percent = (
                            (item["fill_price"] - entry_price) / entry_price * Decimal("100")
                        )
                        profit_amount = (
                            (item["fill_price"] - entry_price) * item["quantity"] * multiplier
                        )
                        ledger["realized"] += profit_amount
                    if before_quantity > 0:
                        position_fraction = min(Decimal("1"), item["quantity"] / before_quantity)
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
                        position_quantity=position_quantity,
                        position_average_cost=position_average_cost,
                        strategy_type=item.get("strategy_type"),
                        strategy_display=item.get("strategy_display"),
                        strategy_price_kind=item.get("strategy_price_kind"),
                        strategy_legs=tuple(item.get("strategy_legs") or ()),
                    )
                )
            return tuple(events)

    async def mark_notified(self, event: MoomooActivityEvent) -> None:
        async with self.database.session() as session:
            if event.kind == "FILL":
                record_ids = event.record_ids or (event.record_id,)
                rows = list(
                    await session.scalars(
                        select(MoomooActivityFill).where(MoomooActivityFill.id.in_(record_ids))
                    )
                )
                notified_at = utc_now()
                for row in rows:
                    row.notified_at = notified_at
            await session.commit()

    async def prepare_daily_summary(
        self, session_date: date, *, force: bool = False
    ) -> MoomooDailySummaryClaim | None:
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
            if existing is not None and existing.published_at is not None and not force:
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
            all_fills = tuple(
                (
                    await session.scalars(
                        select(MoomooActivityFill)
                        .where(MoomooActivityFill.guild_id == self.guild_id)
                        .order_by(
                            MoomooActivityFill.executed_at.asc(),
                            MoomooActivityFill.created_at.asc(),
                        )
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
            previous_equity: dict[str, Decimal] = {}
            if previous is not None:
                previous_fills = tuple(
                    item
                    for item in all_fills
                    if item.executed_at.astimezone(ET).date() == previous.session_date
                )
                previous_fees: dict[str, Decimal] = {}
                for group in _group_fills(previous_fills):
                    label = _account_label(str(group["account_ref"]))
                    previous_fees[label] = previous_fees.get(label, Decimal("0")) + _group_fee(
                        group, self.fee_schedule
                    )
                for item in previous.snapshot_json.get("accounts", []):
                    account = str(item.get("account") or "")
                    if not account or item.get("equity") is None:
                        continue
                    if item.get("post_fee_equity") is not None:
                        previous_equity[account] = Decimal(str(item["post_fee_equity"]))
                    else:
                        previous_equity[account] = Decimal(str(item["equity"])) - previous_fees.get(
                            account, Decimal("0")
                        )
            if latest.get("daily_open_date") == session_date.isoformat():
                previous_equity = {
                    str(item.get("account")): Decimal(str(item["equity"]))
                    for item in latest.get("daily_open_accounts", [])
                    if item.get("account") and item.get("equity") is not None
                }
            fees_by_account: dict[str, Decimal] = {}
            for group in _group_fills(fills):
                label = _account_label(str(group["account_ref"]))
                fees_by_account[label] = fees_by_account.get(label, Decimal("0")) + _group_fee(
                    group, self.fee_schedule
                )
            accounts = []
            for item in latest.get("accounts", []):
                current = dict(item)
                account = str(current.get("account"))
                prior = previous_equity.get(account)
                equity_raw = current.get("equity")
                fee = fees_by_account.get(account, Decimal("0"))
                current["commission"] = _money(fee)
                current["fee_basis"] = "MOOMOO_CA_PUBLIC_RATE"
                if equity_raw is not None:
                    equity = Decimal(str(equity_raw))
                    net_equity = equity - fee
                    current["pre_fee_equity"] = _money(equity)
                    current["post_fee_equity"] = _money(net_equity)
                    if prior not in (None, Decimal("0")):
                        gross_profit = equity - prior
                        net_profit = net_equity - prior
                        current["opening_equity"] = _money(prior)
                        current["pre_fee_profit"] = _money(gross_profit)
                        current["pre_fee_return_percent"] = _number(
                            gross_profit / prior * Decimal("100")
                        )
                        current["post_fee_profit"] = _money(net_profit)
                        current["post_fee_return_percent"] = _number(
                            net_profit / prior * Decimal("100")
                        )
                accounts.append(current)
            closed_returns = tuple(
                value
                for closed_at, value in _closed_trade_returns(all_fills)
                if closed_at.astimezone(ET).date() == session_date
            )
            winning_returns = tuple(value for value in closed_returns if value > 0)
            losing_returns = tuple(value for value in closed_returns if value < 0)
            performance = {
                "closed_count": len(closed_returns),
                "win_count": len(winning_returns),
                "win_rate": (
                    _number(
                        Decimal(len(winning_returns))
                        / Decimal(len(closed_returns))
                        * Decimal("100")
                    )
                    if closed_returns
                    else None
                ),
                "average_win": (
                    _number(sum(winning_returns, Decimal("0")) / Decimal(len(winning_returns)))
                    if winning_returns
                    else None
                ),
                "average_loss": (
                    _number(sum(losing_returns, Decimal("0")) / Decimal(len(losing_returns)))
                    if losing_returns
                    else None
                ),
                "basis": "CLOSED_CYCLES_BEFORE_FEES",
            }
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
                "performance": performance,
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

    async def mark_summary_published(self, summary_id: uuid.UUID, message_ids: list[int]) -> None:
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
                    "unrealized_pnl_ratio": _number(item.unrealized_pnl_ratio)
                    if item.unrealized_pnl_ratio is not None
                    else None,
                    "strategy_type": item.strategy_type,
                    "position_type": item.position_type,
                }
                for item in snapshot.positions
            ],
        }
