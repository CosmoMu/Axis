from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.domain.personal_execution import (
    PersonalBrokerEnvironment,
    PersonalExecutionMode,
    PersonalQuote,
)

ET = ZoneInfo("America/New_York")


class PersonalBrokerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    account_ref: str
    equity: Decimal | None
    buying_power: Decimal | None
    cash: Decimal | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    contract_code: str
    quantity: int
    sellable_quantity: int
    average_cost: Decimal
    current_price: Decimal | None
    realized_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    broker_order_id: str
    contract_code: str
    side: str
    quantity: int
    filled_quantity: int
    limit_price: Decimal | None
    average_fill_price: Decimal | None
    status: str
    remark: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class BrokerFill:
    broker_fill_id: str
    broker_order_id: str | None
    contract_code: str
    side: str
    quantity: int
    fill_price: Decimal
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class BrokerOrderAck:
    broker_order_id: str
    status: str
    submitted_at: datetime


class PersonalBroker(Protocol):
    async def read_account(self) -> BrokerAccount: ...

    async def read_positions(self) -> tuple[BrokerPosition, ...]: ...

    async def read_orders(self) -> tuple[BrokerOrder, ...]: ...

    async def read_fills(self) -> tuple[BrokerFill, ...]: ...

    async def read_quote(self, contract_code: str) -> PersonalQuote: ...

    async def place_limit_order(
        self,
        *,
        contract_code: str,
        side: str,
        quantity: int,
        limit_price: Decimal,
        purpose: str,
        idempotency_key: str,
    ) -> BrokerOrderAck: ...

    async def cancel_order(self, broker_order_id: str) -> None: ...


def mask_account_id(value: object) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise PersonalBrokerError("MOOMOO_ACCOUNT_UNAVAILABLE")
    return "acct_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _enum_name(value: object) -> str:
    rendered = str(value or "").strip()
    return rendered.rsplit(".", 1)[-1].upper()


def _decimal(value: object, *, allow_zero: bool = True) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
        return None
    return parsed


def _signed_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _integer(value: object) -> int:
    parsed = _decimal(value)
    return max(0, int(parsed or 0))


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=ET)
    if not isinstance(value, str) or not value.strip():
        return None
    for pattern in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f %Z",
    ):
        with suppress(ValueError):
            return datetime.strptime(value.strip(), pattern).replace(tzinfo=ET)
    return None


def _rows(frame: object) -> tuple[dict[str, Any], ...]:
    if not hasattr(frame, "iterrows"):
        return ()
    return tuple(row.to_dict() for _, row in frame.iterrows())


def _status(value: object) -> str:
    name = _enum_name(value)
    if name in {"SUBMITTED", "SUBMITTING", "WAITING_SUBMIT"}:
        return "SUBMITTED"
    if name in {"FILLED_PART", "PARTIALLY_FILLED"}:
        return "PARTIALLY_FILLED"
    if name in {"FILLED_ALL", "FILLED"}:
        return "FILLED"
    if "CANCEL" in name or name in {"DELETED", "DISABLED"}:
        return "CANCELLED"
    if "FAIL" in name or "REJECT" in name:
        return "REJECTED"
    return "PENDING"


class MoomooPersonalBroker:
    """Owner-only Moomoo adapter; account identifiers never leave this boundary unmasked."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        environment: PersonalBrokerEnvironment,
        execution_mode: PersonalExecutionMode,
        account_id: str | None = None,
        security_firm: str | None = None,
        live_write_validated: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.environment = environment
        self.execution_mode = execution_mode
        self.account_id = account_id.strip() if account_id else None
        self.security_firm = security_firm.strip().upper() if security_firm else None
        self.live_write_validated = live_write_validated
        self._resolved_account_id: int | None = None

    async def read_account(self) -> BrokerAccount:
        return await asyncio.to_thread(self._read_account_sync)

    async def read_positions(self) -> tuple[BrokerPosition, ...]:
        return await asyncio.to_thread(self._read_positions_sync)

    async def read_orders(self) -> tuple[BrokerOrder, ...]:
        return await asyncio.to_thread(self._read_orders_sync)

    async def read_fills(self) -> tuple[BrokerFill, ...]:
        return await asyncio.to_thread(self._read_fills_sync)

    async def read_quote(self, contract_code: str) -> PersonalQuote:
        return await asyncio.to_thread(self._read_quote_sync, contract_code)

    async def place_limit_order(
        self,
        *,
        contract_code: str,
        side: str,
        quantity: int,
        limit_price: Decimal,
        purpose: str,
        idempotency_key: str,
    ) -> BrokerOrderAck:
        if self.execution_mode is not PersonalExecutionMode.LIVE:
            raise PersonalBrokerError("BROKER_WRITE_BLOCKED_DRY_RUN")
        if not self.live_write_validated:
            raise PersonalBrokerError("BROKER_WRITE_BLOCKED_LIVE_NOT_VALIDATED")
        return await asyncio.to_thread(
            self._place_limit_order_sync,
            contract_code,
            side,
            quantity,
            limit_price,
            purpose,
            idempotency_key,
        )

    async def cancel_order(self, broker_order_id: str) -> None:
        if self.execution_mode is not PersonalExecutionMode.LIVE:
            raise PersonalBrokerError("BROKER_WRITE_BLOCKED_DRY_RUN")
        if not self.live_write_validated:
            raise PersonalBrokerError("BROKER_WRITE_BLOCKED_LIVE_NOT_VALIDATED")
        await asyncio.to_thread(self._cancel_order_sync, broker_order_id)

    def _sdk(self) -> dict[str, Any]:
        try:
            from moomoo import (
                RET_OK,
                ModifyOrderOp,
                OpenQuoteContext,
                OpenSecTradeContext,
                OrderType,
                SecurityFirm,
                SysConfig,
                TrdEnv,
                TrdMarket,
                TrdSide,
            )
        except Exception as exc:
            raise PersonalBrokerError("MOOMOO_SDK_UNAVAILABLE") from exc
        SysConfig.enable_console_log(False)
        return {
            "RET_OK": RET_OK,
            "ModifyOrderOp": ModifyOrderOp,
            "OpenQuoteContext": OpenQuoteContext,
            "OpenSecTradeContext": OpenSecTradeContext,
            "OrderType": OrderType,
            "SecurityFirm": SecurityFirm,
            "TrdEnv": TrdEnv,
            "TrdMarket": TrdMarket,
            "TrdSide": TrdSide,
        }

    def _trade_context(self, sdk: dict[str, Any]) -> Any:
        firm = getattr(sdk["SecurityFirm"], self.security_firm or "NONE", None)
        if firm is None:
            raise PersonalBrokerError("MOOMOO_SECURITY_FIRM_INVALID")
        return sdk["OpenSecTradeContext"](
            filter_trdmarket=sdk["TrdMarket"].NONE,
            host=self.host,
            port=self.port,
            security_firm=firm,
        )

    def _trd_env(self, sdk: dict[str, Any]) -> Any:
        return getattr(sdk["TrdEnv"], self.environment.value)

    def _select_account(self, context: Any, sdk: dict[str, Any]) -> int:
        if self._resolved_account_id is not None:
            return self._resolved_account_id
        ret, frame = context.get_acc_list()
        if ret != sdk["RET_OK"]:
            raise PersonalBrokerError("MOOMOO_ACCOUNT_LIST_FAILED")
        expected_environment = self.environment.value
        candidates = []
        for row in _rows(frame):
            account_id = row.get("acc_id")
            if account_id is None or _enum_name(row.get("trd_env")) != expected_environment:
                continue
            if _enum_name(row.get("acc_role")) == "MASTER":
                continue
            raw_markets = row.get("trdmarket_auth") or []
            markets = (
                {_enum_name(item) for item in raw_markets}
                if isinstance(raw_markets, (list, tuple))
                else {_enum_name(item) for item in str(raw_markets).strip("[]").split(",")}
            )
            if "US" not in markets:
                continue
            if self.account_id and str(account_id) != self.account_id:
                continue
            candidates.append(int(account_id))
        if len(candidates) != 1:
            code = "MOOMOO_ACCOUNT_REQUIRED" if candidates else "MOOMOO_ACCOUNT_UNAVAILABLE"
            raise PersonalBrokerError(code)
        self._resolved_account_id = candidates[0]
        return candidates[0]

    def _with_trade(self, callback: Any) -> Any:
        sdk = self._sdk()
        context = None
        try:
            context = self._trade_context(sdk)
            account_id = self._select_account(context, sdk)
            return callback(context, account_id, sdk)
        except PersonalBrokerError:
            raise
        except Exception as exc:
            raise PersonalBrokerError("MOOMOO_TRADE_CONNECTION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    def _read_account_sync(self) -> BrokerAccount:
        def query(context: Any, account_id: int, sdk: dict[str, Any]) -> BrokerAccount:
            ret, frame = context.accinfo_query(
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
                refresh_cache=True,
            )
            rows = _rows(frame)
            if ret != sdk["RET_OK"] or not rows:
                raise PersonalBrokerError("MOOMOO_ACCOUNT_READ_FAILED")
            row = rows[0]
            equity = _decimal(row.get("total_assets"))
            buying_power = _decimal(row.get("power"))
            if buying_power is None:
                buying_power = _decimal(row.get("buying_power"))
            cash = _decimal(row.get("cash"))
            if buying_power is None:
                initial_margin = _decimal(row.get("initial_margin"))
                if equity is not None and initial_margin is not None:
                    buying_power = max(Decimal("0"), equity - initial_margin)
            return BrokerAccount(
                account_ref=mask_account_id(account_id),
                equity=equity,
                buying_power=buying_power,
                cash=cash,
                observed_at=datetime.now(UTC),
            )

        return self._with_trade(query)

    def _read_positions_sync(self) -> tuple[BrokerPosition, ...]:
        def query(context: Any, account_id: int, sdk: dict[str, Any]) -> tuple[BrokerPosition, ...]:
            ret, frame = context.position_list_query(
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
                refresh_cache=True,
            )
            if ret != sdk["RET_OK"]:
                raise PersonalBrokerError("MOOMOO_POSITION_LIST_FAILED")
            output = []
            for row in _rows(frame):
                quantity = _integer(row.get("qty"))
                average_cost = _decimal(row.get("average_cost"), allow_zero=False)
                code = str(row.get("code") or "").strip().upper()
                if not code or quantity <= 0 or average_cost is None:
                    continue
                output.append(
                    BrokerPosition(
                        contract_code=code,
                        quantity=quantity,
                        sellable_quantity=_integer(row.get("can_sell_qty")),
                        average_cost=average_cost,
                        current_price=_decimal(row.get("nominal_price"), allow_zero=False),
                        realized_pnl=_signed_decimal(row.get("realized_pl")),
                    )
                )
            return tuple(output)

        return self._with_trade(query)

    def _read_orders_sync(self) -> tuple[BrokerOrder, ...]:
        def query(context: Any, account_id: int, sdk: dict[str, Any]) -> tuple[BrokerOrder, ...]:
            ret, frame = context.order_list_query(
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
                refresh_cache=True,
            )
            if ret != sdk["RET_OK"]:
                raise PersonalBrokerError("MOOMOO_ORDER_LIST_FAILED")
            return tuple(
                BrokerOrder(
                    broker_order_id=str(row.get("order_id") or ""),
                    contract_code=str(row.get("code") or "").strip().upper(),
                    side=_enum_name(row.get("trd_side")),
                    quantity=_integer(row.get("qty")),
                    filled_quantity=_integer(row.get("dealt_qty")),
                    limit_price=_decimal(row.get("price"), allow_zero=False),
                    average_fill_price=_decimal(row.get("dealt_avg_price"), allow_zero=False),
                    status=_status(row.get("order_status")),
                    remark=str(row.get("remark") or "") or None,
                    updated_at=_timestamp(row.get("updated_time") or row.get("create_time")),
                )
                for row in _rows(frame)
                if row.get("order_id") is not None
            )

        return self._with_trade(query)

    def _read_fills_sync(self) -> tuple[BrokerFill, ...]:
        def query(context: Any, account_id: int, sdk: dict[str, Any]) -> tuple[BrokerFill, ...]:
            ret, frame = context.deal_list_query(
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
                refresh_cache=True,
            )
            if ret != sdk["RET_OK"]:
                raise PersonalBrokerError("MOOMOO_FILL_LIST_FAILED")
            output = []
            for row in _rows(frame):
                fill_id = str(row.get("deal_id") or "").strip()
                quantity = _integer(row.get("qty"))
                price = _decimal(row.get("price"), allow_zero=False)
                executed = _timestamp(row.get("create_time"))
                if not fill_id or quantity <= 0 or price is None or executed is None:
                    continue
                output.append(
                    BrokerFill(
                        broker_fill_id=fill_id,
                        broker_order_id=str(row.get("order_id") or "") or None,
                        contract_code=str(row.get("code") or "").strip().upper(),
                        side=_enum_name(row.get("trd_side")),
                        quantity=quantity,
                        fill_price=price,
                        executed_at=executed,
                    )
                )
            return tuple(output)

        return self._with_trade(query)

    def _read_quote_sync(self, contract_code: str) -> PersonalQuote:
        sdk = self._sdk()
        context = None
        try:
            context = sdk["OpenQuoteContext"](host=self.host, port=self.port)
            ret, frame = context.get_market_snapshot([contract_code])
            rows = _rows(frame)
            if ret != sdk["RET_OK"] or not rows:
                raise PersonalBrokerError("MOOMOO_QUOTE_UNAVAILABLE")
            row = rows[0]
            bid = _decimal(row.get("bid_price"), allow_zero=False)
            ask = _decimal(row.get("ask_price"), allow_zero=False)
            observed_at = _timestamp(row.get("update_time"))
            if bid is None or ask is None or observed_at is None or ask < bid:
                raise PersonalBrokerError("MOOMOO_QUOTE_INVALID")
            return PersonalQuote(
                contract_code=contract_code,
                bid=bid,
                ask=ask,
                last=_decimal(row.get("last_price"), allow_zero=False),
                observed_at=observed_at,
                volume=_integer(row.get("volume")) or None,
                open_interest=_integer(row.get("option_open_interest")) or None,
            )
        except PersonalBrokerError:
            raise
        except Exception as exc:
            raise PersonalBrokerError("MOOMOO_QUOTE_CONNECTION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    def _place_limit_order_sync(
        self,
        contract_code: str,
        side: str,
        quantity: int,
        limit_price: Decimal,
        purpose: str,
        idempotency_key: str,
    ) -> BrokerOrderAck:
        def submit(context: Any, account_id: int, sdk: dict[str, Any]) -> BrokerOrderAck:
            trading_side = getattr(sdk["TrdSide"], side)
            ret, frame = context.place_order(
                price=float(limit_price),
                qty=quantity,
                code=contract_code,
                trd_side=trading_side,
                order_type=sdk["OrderType"].NORMAL,
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
                remark=f"AXIS-{purpose}-{idempotency_key[:12]}",
            )
            rows = _rows(frame)
            if ret != sdk["RET_OK"] or not rows:
                raise PersonalBrokerError("BROKER_ORDER_REJECTED")
            row = rows[0]
            broker_order_id = str(row.get("order_id") or "").strip()
            if not broker_order_id:
                raise PersonalBrokerError("BROKER_ACK_INVALID")
            return BrokerOrderAck(
                broker_order_id=broker_order_id,
                status=_status(row.get("order_status")),
                submitted_at=datetime.now(UTC),
            )

        return self._with_trade(submit)

    def _cancel_order_sync(self, broker_order_id: str) -> None:
        def cancel(context: Any, account_id: int, sdk: dict[str, Any]) -> None:
            ret, _ = context.modify_order(
                modify_order_op=sdk["ModifyOrderOp"].CANCEL,
                order_id=broker_order_id,
                qty=0,
                price=0,
                trd_env=self._trd_env(sdk),
                acc_id=account_id,
            )
            if ret != sdk["RET_OK"]:
                raise PersonalBrokerError("BROKER_ORDER_CANCEL_FAILED")

        self._with_trade(cancel)
