from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class PersonalExecutionMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"


class PersonalBrokerEnvironment(StrEnum):
    SIMULATE = "SIMULATE"
    REAL = "REAL"


class PersonalFollowScope(StrEnum):
    OWNER_ONLY = "OWNER_ONLY"
    ALL_ELIGIBLE_SIGNALS = "ALL_ELIGIBLE_SIGNALS"


class PersonalPositionSource(StrEnum):
    AXIS_AUTO = "AXIS_AUTO"
    MANUAL_MOOMOO = "MANUAL_MOOMOO"
    AXIS_AUTO_MANUAL_ADD = "AXIS_AUTO_MANUAL_ADD"


class PersonalPositionStatus(StrEnum):
    PENDING_ENTRY = "PENDING_ENTRY"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    ACTIVE = "ACTIVE"
    BREAKEVEN_PROTECTED = "BREAKEVEN_PROTECTED"
    TRAILING = "TRAILING"
    RUNNER = "RUNNER"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    ENTRY_EXPIRED = "ENTRY_EXPIRED"
    CANCELLED_ENTRY = "CANCELLED_ENTRY"
    BROKER_REJECTED = "BROKER_REJECTED"
    SYNC_ERROR = "SYNC_ERROR"


class PersonalRiskStage(StrEnum):
    INITIAL = "INITIAL"
    BREAKEVEN = "BREAKEVEN"
    TRAILING = "TRAILING"
    RUNNER = "RUNNER"
    PAUSED = "PAUSED"


class PersonalOrderPurpose(StrEnum):
    ENTRY = "ENTRY"
    TP50 = "TP50"
    TP100 = "TP100"
    STOP_EXIT = "STOP_EXIT"
    TRAILING_EXIT = "TRAILING_EXIT"
    SWING_CLOSE_EXIT = "SWING_CLOSE_EXIT"


class PersonalOrderStatus(StrEnum):
    DRY_RUN_VALIDATED = "DRY_RUN_VALIDATED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PersonalExecutionPolicy:
    position_equity_pct: Decimal = Decimal("0.10")
    position_budget_min: Decimal = Decimal("200")
    position_budget_max: Decimal = Decimal("500")
    entry_max_chase_pct: Decimal = Decimal("0.05")
    trailing_stop_pct: Decimal = Decimal("0.30")
    max_quote_age_seconds: int = 15
    max_bid_ask_spread_pct: Decimal = Decimal("0.20")
    minimum_option_volume: int | None = None
    minimum_open_interest: int | None = None
    short_term_entry_ttl_minutes: int = 5
    swing_entry_ttl_minutes: int = 30
    market_open_guard_enabled: bool = True
    market_open_guard_minutes: int = 5

    def __post_init__(self) -> None:
        if not Decimal("0") < self.position_equity_pct <= ONE:
            raise ValueError("POSITION_EQUITY_PCT_INVALID")
        if (
            self.position_budget_min <= 0
            or self.position_budget_max < self.position_budget_min
        ):
            raise ValueError("POSITION_BUDGET_INVALID")
        if not Decimal("0") <= self.entry_max_chase_pct <= ONE:
            raise ValueError("ENTRY_MAX_CHASE_PCT_INVALID")
        if not Decimal("0") < self.trailing_stop_pct < ONE:
            raise ValueError("TRAILING_STOP_PCT_INVALID")
        if self.max_quote_age_seconds <= 0 or self.market_open_guard_minutes < 0:
            raise ValueError("PERSONAL_EXECUTION_TIMING_INVALID")
        if self.minimum_option_volume is not None and self.minimum_option_volume < 0:
            raise ValueError("MINIMUM_OPTION_VOLUME_INVALID")
        if self.minimum_open_interest is not None and self.minimum_open_interest < 0:
            raise ValueError("MINIMUM_OPEN_INTEREST_INVALID")

    def configured_budget(self, equity: Decimal) -> Decimal:
        target = equity * self.position_equity_pct
        return max(
            self.position_budget_min,
            min(self.position_budget_max, target),
        )

    def effective_budget(self, equity: Decimal, buying_power: Decimal) -> Decimal:
        return max(Decimal("0"), min(self.configured_budget(equity), buying_power))

    def max_entry_price(self, published_entry: Decimal) -> Decimal:
        if published_entry <= 0:
            raise ValueError("PUBLISHED_ENTRY_PRICE_INVALID")
        return (published_entry * (ONE + self.entry_max_chase_pct)).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )

    @staticmethod
    def entry_quantity(effective_budget: Decimal, limit_price: Decimal) -> int:
        if effective_budget <= 0 or limit_price <= 0:
            return 0
        return int((effective_budget / (limit_price * HUNDRED)).to_integral_value(
            rounding=ROUND_DOWN
        ))

    def entry_ttl_minutes(self, category: str) -> int:
        return (
            self.short_term_entry_ttl_minutes
            if category == "SHORT_TERM"
            else self.swing_entry_ttl_minutes
        )

    def in_opening_guard(self, observed_at: datetime) -> bool:
        if not self.market_open_guard_enabled or self.market_open_guard_minutes <= 0:
            return False
        local = observed_at.astimezone(ET)
        if local.weekday() >= 5:
            return False
        opened = datetime.combine(local.date(), time(9, 30), tzinfo=ET)
        return opened <= local < opened + timedelta(minutes=self.market_open_guard_minutes)

    @staticmethod
    def allocation(original_quantity: int) -> tuple[int, int, int]:
        if original_quantity <= 1:
            return 0, 0, max(0, original_quantity)
        tp50 = original_quantity // 2
        runner = 1
        tp100 = max(0, original_quantity - tp50 - runner)
        return tp50, tp100, runner


@dataclass(frozen=True, slots=True)
class PersonalQuote:
    contract_code: str
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    observed_at: datetime
    volume: int | None = None
    open_interest: int | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_pct(self) -> Decimal:
        mid = self.mid
        return (self.ask - self.bid) / mid if mid > 0 else Decimal("999")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    stage: PersonalRiskStage
    risk_high: Decimal
    protection: Decimal
    return_pct: Decimal
    order_purpose: PersonalOrderPurpose | None = None
    sell_quantity: int = 0
    opening_guard: bool = False


def return_pct(average_cost: Decimal, price: Decimal) -> Decimal:
    if average_cost <= 0:
        raise ValueError("AVERAGE_COST_INVALID")
    return (price / average_cost - ONE) * HUNDRED


def evaluate_risk(
    *,
    policy: PersonalExecutionPolicy,
    average_cost: Decimal,
    current_price: Decimal,
    current_quantity: int,
    original_quantity: int,
    prior_stage: PersonalRiskStage,
    prior_risk_high: Decimal,
    tp50_executed: bool,
    tp100_executed: bool,
    observed_at: datetime,
) -> RiskDecision:
    if current_quantity <= 0 or average_cost <= 0 or current_price <= 0:
        raise ValueError("RISK_INPUT_INVALID")
    current_return = return_pct(average_cost, current_price)
    if policy.in_opening_guard(observed_at):
        protection = (
            average_cost * (ONE - Decimal("0.30"))
            if prior_stage == PersonalRiskStage.INITIAL
            else average_cost
            if prior_stage == PersonalRiskStage.BREAKEVEN
            else prior_risk_high * (ONE - policy.trailing_stop_pct)
        )
        return RiskDecision(
            stage=prior_stage,
            risk_high=prior_risk_high,
            protection=protection,
            return_pct=current_return,
            opening_guard=True,
        )

    risk_high = max(prior_risk_high, current_price)
    if prior_stage in {PersonalRiskStage.TRAILING, PersonalRiskStage.RUNNER}:
        protection = risk_high * (ONE - policy.trailing_stop_pct)
        if current_price <= protection:
            return RiskDecision(
                stage=prior_stage,
                risk_high=risk_high,
                protection=protection,
                return_pct=current_return,
                order_purpose=PersonalOrderPurpose.TRAILING_EXIT,
                sell_quantity=current_quantity,
            )
    elif prior_stage == PersonalRiskStage.BREAKEVEN:
        if current_price <= average_cost:
            return RiskDecision(
                stage=prior_stage,
                risk_high=risk_high,
                protection=average_cost,
                return_pct=current_return,
                order_purpose=PersonalOrderPurpose.STOP_EXIT,
                sell_quantity=current_quantity,
            )
    elif current_return <= Decimal("-30"):
        return RiskDecision(
            stage=prior_stage,
            risk_high=risk_high,
            protection=average_cost * Decimal("0.70"),
            return_pct=current_return,
            order_purpose=PersonalOrderPurpose.STOP_EXIT,
            sell_quantity=current_quantity,
        )

    if current_return >= Decimal("50") or prior_stage in {
        PersonalRiskStage.TRAILING,
        PersonalRiskStage.RUNNER,
    }:
        stage = (
            PersonalRiskStage.RUNNER
            if current_quantity == 1 and tp100_executed
            else PersonalRiskStage.TRAILING
        )
        protection = risk_high * (ONE - policy.trailing_stop_pct)
        if original_quantity > 1 and not tp50_executed:
            tp50_qty, _, _ = policy.allocation(original_quantity)
            quantity = min(tp50_qty, max(0, current_quantity - 1))
            if quantity:
                return RiskDecision(
                    stage=stage,
                    risk_high=risk_high,
                    protection=protection,
                    return_pct=current_return,
                    order_purpose=PersonalOrderPurpose.TP50,
                    sell_quantity=quantity,
                )
        if (
            current_return >= Decimal("100")
            and original_quantity > 2
            and tp50_executed
            and not tp100_executed
        ):
            _, tp100_qty, _ = policy.allocation(original_quantity)
            quantity = min(tp100_qty, max(0, current_quantity - 1))
            if quantity:
                return RiskDecision(
                    stage=stage,
                    risk_high=risk_high,
                    protection=protection,
                    return_pct=current_return,
                    order_purpose=PersonalOrderPurpose.TP100,
                    sell_quantity=quantity,
                )
        return RiskDecision(stage, risk_high, protection, current_return)

    if current_return >= Decimal("30") or prior_stage == PersonalRiskStage.BREAKEVEN:
        return RiskDecision(
            PersonalRiskStage.BREAKEVEN,
            risk_high,
            average_cost,
            current_return,
        )
    return RiskDecision(
        PersonalRiskStage.INITIAL,
        risk_high,
        average_cost * Decimal("0.70"),
        current_return,
    )
