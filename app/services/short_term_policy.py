from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


class ShortTermPolicyError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class MilestoneRule:
    return_pct: int
    card_type: str


@dataclass(frozen=True, slots=True)
class MomentumTriggerRule:
    seconds: int
    drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class ShortTermTrackingPolicy:
    version: str
    price_source: str
    poll_seconds: int
    max_quote_age_seconds: int
    last_trade_quote_guard_pct: Decimal
    milestones: tuple[MilestoneRule, ...]
    initial_reference_return_pct: int
    reference_moves: tuple[tuple[int, int], ...]
    momentum_enabled: bool
    momentum_min_profit_pct: Decimal
    momentum_cooldown: timedelta
    momentum_triggers: tuple[MomentumTriggerRule, ...]

    @classmethod
    def load(cls, path: Path) -> ShortTermTrackingPolicy:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ShortTermPolicyError("SHORT_TERM_POLICY_LOAD_FAILED") from exc
        if not isinstance(payload, dict):
            raise ShortTermPolicyError("SHORT_TERM_POLICY_INVALID")
        try:
            milestones = tuple(
                MilestoneRule(int(item["return_pct"]), str(item["card_type"]).upper())
                for item in payload["milestones"]
            )
            protection = payload["reference_protection"]
            moves = tuple(
                sorted(
                    (int(milestone), int(reference))
                    for milestone, reference in protection["moves"].items()
                )
            )
            momentum = payload["momentum_reversal"]
            triggers = tuple(
                MomentumTriggerRule(
                    seconds=int(item["seconds"]),
                    drawdown_pct=_decimal(item["drawdown_pct"]),
                )
                for item in momentum["triggers"]
            )
            policy = cls(
                version=str(payload["version"]),
                price_source=str(payload["price_source"]).upper(),
                poll_seconds=int(payload["poll_seconds"]),
                max_quote_age_seconds=int(payload["max_quote_age_seconds"]),
                last_trade_quote_guard_pct=_decimal(payload["last_trade_quote_guard_pct"]),
                milestones=milestones,
                initial_reference_return_pct=int(protection["initial_return_pct"]),
                reference_moves=moves,
                momentum_enabled=bool(momentum["enabled"]),
                momentum_min_profit_pct=_decimal(momentum["min_profit_pct"]),
                momentum_cooldown=timedelta(minutes=int(momentum["cooldown_minutes"])),
                momentum_triggers=triggers,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ShortTermPolicyError("SHORT_TERM_POLICY_INVALID") from exc
        policy.validate()
        return policy

    def validate(self) -> None:
        milestone_values = [item.return_pct for item in self.milestones]
        if (
            not self.version.startswith("ST_TRACKING_V")
            or self.price_source not in {"BID", "MID", "LAST"}
            or self.poll_seconds <= 0
            or self.max_quote_age_seconds <= 0
            or self.last_trade_quote_guard_pct <= 0
            or milestone_values != sorted(set(milestone_values))
            or any(item.return_pct <= 0 for item in self.milestones)
            or any(item.card_type not in {"TP", "RUNNER"} for item in self.milestones)
            or self.initial_reference_return_pct >= 0
            or any(
                trigger.seconds <= 0 or trigger.drawdown_pct <= 0
                for trigger in self.momentum_triggers
            )
        ):
            raise ShortTermPolicyError("SHORT_TERM_POLICY_INVALID")
        allowed = set(milestone_values)
        for milestone, reference in self.reference_moves:
            if milestone not in allowed or reference < 0 or reference >= milestone:
                raise ShortTermPolicyError("SHORT_TERM_POLICY_INVALID")

    @staticmethod
    def return_pct(entry_price: Decimal, price: Decimal) -> Decimal:
        if entry_price <= 0 or price <= 0:
            raise ShortTermPolicyError("SHORT_TERM_PRICE_INVALID")
        return ((price - entry_price) / entry_price) * Decimal("100")

    @staticmethod
    def price_at_return(entry_price: Decimal, return_pct: Decimal | int) -> Decimal:
        return entry_price * (Decimal("1") + Decimal(return_pct) / Decimal("100"))

    def crossed_milestones(
        self,
        current_return_pct: Decimal,
        milestones_hit: set[int],
    ) -> tuple[MilestoneRule, ...]:
        return tuple(
            rule
            for rule in self.milestones
            if rule.return_pct not in milestones_hit
            and current_return_pct >= Decimal(rule.return_pct)
        )

    def reference_for(self, entry_price: Decimal, milestones_hit: set[int]) -> tuple[Decimal, int]:
        reference_return = self.initial_reference_return_pct
        for milestone, candidate in self.reference_moves:
            if milestone in milestones_hit:
                reference_return = candidate
        return self.price_at_return(entry_price, reference_return), reference_return

    def momentum_drawdown(
        self,
        *,
        high_price: Decimal,
        high_return_pct: Decimal,
        current_price: Decimal,
        elapsed_seconds: int,
    ) -> tuple[Decimal, int] | None:
        if (
            not self.momentum_enabled
            or high_price <= 0
            or current_price <= 0
            or high_return_pct < self.momentum_min_profit_pct
            or elapsed_seconds < 0
        ):
            return None
        drawdown = ((high_price - current_price) / high_price) * Decimal("100")
        for trigger in sorted(self.momentum_triggers, key=lambda item: item.seconds):
            if elapsed_seconds <= trigger.seconds and drawdown >= trigger.drawdown_pct:
                return drawdown, trigger.seconds
        return None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))
