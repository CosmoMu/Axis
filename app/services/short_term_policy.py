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
class TpLevelRule:
    label: str
    return_pct: int


@dataclass(frozen=True, slots=True)
class MomentumTriggerRule:
    seconds: int
    drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class ShortTermTrackingPolicy:
    version: str
    price_source: str
    tracking_exit_mode: str
    poll_seconds: int
    max_quote_age_seconds: int
    last_trade_quote_guard_pct: Decimal
    tp_levels: tuple[TpLevelRule, ...]
    initial_protection_return_pct: int
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
            tp_levels = tuple(
                TpLevelRule(str(label).upper(), int(return_pct))
                for label, return_pct in payload["tp_levels"].items()
            )
            tracking_exit_mode = str(
                payload.get("tracking_exit_mode", "LEGACY_PROTECTION")
            ).upper()
            protection = payload.get("tracking_protection", {})
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
                tracking_exit_mode=tracking_exit_mode,
                poll_seconds=int(payload["poll_seconds"]),
                max_quote_age_seconds=int(payload["max_quote_age_seconds"]),
                last_trade_quote_guard_pct=_decimal(payload["last_trade_quote_guard_pct"]),
                tp_levels=tp_levels,
                initial_protection_return_pct=int(
                    protection.get("initial_return_pct", 0)
                ),
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
        labels = [item.label for item in self.tp_levels]
        return_values = [item.return_pct for item in self.tp_levels]
        expected_labels = [f"TP{index}" for index in range(1, len(labels) + 1)]
        if (
            not self.version.startswith("ST_TRACKING_V")
            or self.price_source not in {"BID", "MID", "LAST"}
            or self.tracking_exit_mode not in {"EXPIRY_ONLY", "LEGACY_PROTECTION"}
            or self.poll_seconds <= 0
            or self.max_quote_age_seconds <= 0
            or self.last_trade_quote_guard_pct <= 0
            or labels != expected_labels
            or return_values != sorted(set(return_values))
            or any(item.return_pct <= 0 for item in self.tp_levels)
            or (
                self.tracking_exit_mode == "LEGACY_PROTECTION"
                and self.initial_protection_return_pct >= 0
            )
            or (
                self.tracking_exit_mode == "EXPIRY_ONLY"
                and self.initial_protection_return_pct != 0
            )
            or any(
                trigger.seconds <= 0 or trigger.drawdown_pct <= 0
                for trigger in self.momentum_triggers
            )
        ):
            raise ShortTermPolicyError("SHORT_TERM_POLICY_INVALID")

    @staticmethod
    def return_pct(entry_price: Decimal, price: Decimal) -> Decimal:
        if entry_price <= 0 or price <= 0:
            raise ShortTermPolicyError("SHORT_TERM_PRICE_INVALID")
        return ((price - entry_price) / entry_price) * Decimal("100")

    @staticmethod
    def price_at_return(entry_price: Decimal, return_pct: Decimal | int) -> Decimal:
        return entry_price * (Decimal("1") + Decimal(return_pct) / Decimal("100"))

    def crossed_tp_levels(
        self,
        current_return_pct: Decimal,
        tp_levels_hit: set[str],
    ) -> tuple[TpLevelRule, ...]:
        return tuple(
            rule
            for rule in self.tp_levels
            if rule.label not in tp_levels_hit
            and current_return_pct >= Decimal(rule.return_pct)
        )

    def protection_for(
        self,
        entry_price: Decimal,
        tp_levels_hit: set[str],
    ) -> tuple[Decimal, int, str]:
        if self.tracking_exit_mode == "EXPIRY_ONLY":
            return self.sl_alert_reference(entry_price, tp_levels_hit)
        protection_return = self.initial_protection_return_pct
        protection_reason = "INITIAL_TRACKING_PROTECTION"
        highest_index = max(
            (
                index
                for index, rule in enumerate(self.tp_levels)
                if rule.label in tp_levels_hit
            ),
            default=-1,
        )
        if highest_index >= 0 and self.tp_levels[highest_index].return_pct <= 20:
            protection_return = 0
            protection_reason = f"{self.tp_levels[highest_index].label}_ENTRY_PROTECTION"
        elif highest_index > 0:
            previous = self.tp_levels[highest_index - 1]
            protection_return = previous.return_pct
            protection_reason = f"{previous.label}_PROTECTION"
        return (
            self.price_at_return(entry_price, protection_return),
            protection_return,
            protection_reason,
        )

    def sl_alert_reference(
        self,
        entry_price: Decimal,
        tp_levels_hit: set[str],
    ) -> tuple[Decimal, int, str]:
        reached_tp50 = any(
            rule.label in tp_levels_hit and rule.return_pct >= 50
            for rule in self.tp_levels
        )
        if reached_tp50:
            return entry_price, 0, "SL_ALERT_POST_TP50_BREAKEVEN"
        return (
            self.price_at_return(entry_price, -50),
            -50,
            "SL_ALERT_PRE_TP50_NEGATIVE_50",
        )

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
