from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domain.personal_execution import PersonalBrokerEnvironment
from app.integrations.moomoo_personal_execution import (
    PersonalBrokerError,
    _decimal,
    _enum_name,
    _rows,
    _signed_decimal,
    _status,
    _timestamp,
    mask_account_id,
)


@dataclass(frozen=True, slots=True)
class ActivityAccount:
    account_ref: str
    equity: Decimal | None
    buying_power: Decimal | None
    cash: Decimal | None


@dataclass(frozen=True, slots=True)
class ActivityPosition:
    account_ref: str
    instrument_code: str
    quantity: Decimal
    average_cost: Decimal | None
    current_price: Decimal | None
    unrealized_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class ActivityOrder:
    account_ref: str
    broker_order_id: str
    instrument_code: str
    side: str
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal | None
    average_fill_price: Decimal | None
    status: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActivityFill:
    account_ref: str
    broker_fill_id: str
    broker_order_id: str | None
    instrument_code: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    accounts: tuple[ActivityAccount, ...]
    positions: tuple[ActivityPosition, ...]
    orders: tuple[ActivityOrder, ...]
    fills: tuple[ActivityFill, ...]
    observed_at: datetime


def _quantity(value: object) -> Decimal:
    return _decimal(value) or Decimal("0")


class MoomooActivityReader:
    """Read-only multi-account Moomoo adapter.

    This adapter deliberately exposes no order placement, modification, cancellation,
    or trade-unlock methods.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        environment: PersonalBrokerEnvironment,
        security_firm: str,
        account_type: str = "MARGIN",
        account_ids: tuple[str, ...] = (),
    ) -> None:
        self.host = host
        self.port = port
        self.environment = environment
        self.security_firm = security_firm.strip().upper()
        self.account_type = account_type.strip().upper()
        self.account_ids = frozenset(item.strip() for item in account_ids if item.strip())

    async def read_snapshot(self) -> ActivitySnapshot:
        return await asyncio.to_thread(self._read_snapshot_sync)

    def _sdk(self) -> dict[str, Any]:
        try:
            from moomoo import (
                RET_OK,
                Currency,
                OpenSecTradeContext,
                SecurityFirm,
                SysConfig,
                TrdEnv,
                TrdMarket,
            )
        except Exception as exc:
            raise PersonalBrokerError("MOOMOO_SDK_UNAVAILABLE") from exc
        SysConfig.enable_console_log(False)
        return {
            "RET_OK": RET_OK,
            "Currency": Currency,
            "OpenSecTradeContext": OpenSecTradeContext,
            "SecurityFirm": SecurityFirm,
            "TrdEnv": TrdEnv,
            "TrdMarket": TrdMarket,
        }

    def _read_snapshot_sync(self) -> ActivitySnapshot:
        sdk = self._sdk()
        firm = getattr(sdk["SecurityFirm"], self.security_firm, None)
        if firm is None:
            raise PersonalBrokerError("MOOMOO_SECURITY_FIRM_INVALID")
        context = None
        try:
            context = sdk["OpenSecTradeContext"](
                filter_trdmarket=sdk["TrdMarket"].NONE,
                host=self.host,
                port=self.port,
                security_firm=firm,
            )
            account_ids = self._account_ids(context, sdk)
            accounts: list[ActivityAccount] = []
            positions: list[ActivityPosition] = []
            orders: list[ActivityOrder] = []
            fills: list[ActivityFill] = []
            for account_id in account_ids:
                account_ref = mask_account_id(account_id)
                accounts.append(self._read_account(context, sdk, account_id, account_ref))
                positions.extend(self._read_positions(context, sdk, account_id, account_ref))
                orders.extend(self._read_orders(context, sdk, account_id, account_ref))
                fills.extend(self._read_fills(context, sdk, account_id, account_ref))
            return ActivitySnapshot(
                accounts=tuple(accounts),
                positions=tuple(positions),
                orders=tuple(orders),
                fills=tuple(fills),
                observed_at=datetime.now(UTC),
            )
        except PersonalBrokerError:
            raise
        except Exception as exc:
            raise PersonalBrokerError("MOOMOO_ACTIVITY_READ_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    def _account_ids(self, context: Any, sdk: dict[str, Any]) -> tuple[int, ...]:
        ret, frame = context.get_acc_list()
        if ret != sdk["RET_OK"]:
            raise PersonalBrokerError("MOOMOO_ACCOUNT_LIST_FAILED")
        selected: list[int] = []
        for row in _rows(frame):
            raw_id = row.get("acc_id")
            if raw_id is None or _enum_name(row.get("trd_env")) != self.environment.value:
                continue
            if _enum_name(row.get("acc_role")) == "MASTER":
                continue
            if self.account_type and _enum_name(row.get("acc_type")) != self.account_type:
                continue
            raw_markets = row.get("trdmarket_auth") or []
            if isinstance(raw_markets, (list, tuple)):
                markets = {_enum_name(item) for item in raw_markets}
            else:
                markets = {
                    _enum_name(item)
                    for item in str(raw_markets).strip("[]").split(",")
                    if item.strip()
                }
            if "US" not in markets:
                continue
            if self.account_ids and str(raw_id) not in self.account_ids:
                continue
            selected.append(int(raw_id))
        if not selected:
            raise PersonalBrokerError("MOOMOO_ACTIVITY_ACCOUNT_UNAVAILABLE")
        if not self.account_ids and len(selected) != 1:
            raise PersonalBrokerError("MOOMOO_ACTIVITY_ACCOUNT_AMBIGUOUS")
        return tuple(sorted(set(selected)))

    def _trd_env(self, sdk: dict[str, Any]) -> Any:
        return getattr(sdk["TrdEnv"], self.environment.value)

    def _read_account(
        self, context: Any, sdk: dict[str, Any], account_id: int, account_ref: str
    ) -> ActivityAccount:
        ret, frame = context.accinfo_query(
            trd_env=self._trd_env(sdk),
            acc_id=account_id,
            refresh_cache=True,
            currency=sdk["Currency"].USD,
        )
        rows = _rows(frame)
        if ret != sdk["RET_OK"] or not rows:
            raise PersonalBrokerError("MOOMOO_ACCOUNT_READ_FAILED")
        row = rows[0]
        return ActivityAccount(
            account_ref=account_ref,
            equity=_decimal(row.get("total_assets")),
            buying_power=_decimal(row.get("power")) or _decimal(row.get("buying_power")),
            cash=_decimal(row.get("cash")),
        )

    def _read_positions(
        self, context: Any, sdk: dict[str, Any], account_id: int, account_ref: str
    ) -> tuple[ActivityPosition, ...]:
        ret, frame = context.position_list_query(
            trd_env=self._trd_env(sdk), acc_id=account_id, refresh_cache=True
        )
        if ret != sdk["RET_OK"]:
            raise PersonalBrokerError("MOOMOO_POSITION_LIST_FAILED")
        output = []
        for row in _rows(frame):
            code = str(row.get("code") or "").strip().upper()
            quantity = _quantity(row.get("qty"))
            if not code or quantity == 0:
                continue
            output.append(
                ActivityPosition(
                    account_ref=account_ref,
                    instrument_code=code,
                    quantity=quantity,
                    average_cost=_decimal(row.get("average_cost"), allow_zero=False),
                    current_price=_decimal(row.get("nominal_price"), allow_zero=False),
                    unrealized_pnl=_signed_decimal(row.get("pl_val")),
                )
            )
        return tuple(output)

    def _read_orders(
        self, context: Any, sdk: dict[str, Any], account_id: int, account_ref: str
    ) -> tuple[ActivityOrder, ...]:
        ret, frame = context.order_list_query(
            trd_env=self._trd_env(sdk), acc_id=account_id, refresh_cache=True
        )
        if ret != sdk["RET_OK"]:
            raise PersonalBrokerError("MOOMOO_ORDER_LIST_FAILED")
        output = []
        for row in _rows(frame):
            order_id = str(row.get("order_id") or "").strip()
            code = str(row.get("code") or "").strip().upper()
            if not order_id or not code:
                continue
            output.append(
                ActivityOrder(
                    account_ref=account_ref,
                    broker_order_id=order_id,
                    instrument_code=code,
                    side=_enum_name(row.get("trd_side")),
                    quantity=_quantity(row.get("qty")),
                    filled_quantity=_quantity(row.get("dealt_qty")),
                    limit_price=_decimal(row.get("price"), allow_zero=False),
                    average_fill_price=_decimal(row.get("dealt_avg_price"), allow_zero=False),
                    status=_status(row.get("order_status")),
                    updated_at=_timestamp(row.get("updated_time") or row.get("create_time")),
                )
            )
        return tuple(output)

    def _read_fills(
        self, context: Any, sdk: dict[str, Any], account_id: int, account_ref: str
    ) -> tuple[ActivityFill, ...]:
        ret, frame = context.deal_list_query(
            trd_env=self._trd_env(sdk), acc_id=account_id, refresh_cache=True
        )
        if ret != sdk["RET_OK"]:
            raise PersonalBrokerError("MOOMOO_FILL_LIST_FAILED")
        output = []
        for row in _rows(frame):
            fill_id = str(row.get("deal_id") or "").strip()
            code = str(row.get("code") or "").strip().upper()
            quantity = _quantity(row.get("qty"))
            price = _decimal(row.get("price"), allow_zero=False)
            executed_at = _timestamp(row.get("create_time"))
            if not fill_id or not code or quantity <= 0 or price is None or executed_at is None:
                continue
            output.append(
                ActivityFill(
                    account_ref=account_ref,
                    broker_fill_id=fill_id,
                    broker_order_id=str(row.get("order_id") or "").strip() or None,
                    instrument_code=code,
                    side=_enum_name(row.get("trd_side")),
                    quantity=quantity,
                    fill_price=price,
                    executed_at=executed_at,
                )
            )
        return tuple(output)
