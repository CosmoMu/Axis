"""Deterministic confidence factors; LLM output cannot override these values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.market_intelligence.research_engine.models import ResearchPack


def _direction(value: Any) -> int:
    text = str(value or "").upper()
    if "BULL" in text or "偏多" in text or text == "CALL":
        return 1
    if "BEAR" in text or "偏空" in text or text == "PUT":
        return -1
    return 0


def agreement_and_conflict(pack: ResearchPack) -> tuple[float, float]:
    directions: list[int] = []
    for name in ("technical", "gex", "fundamentals", "news_macro", "sentiment"):
        component = pack.component(name)
        if component is None or not component.available:
            continue
        candidate = (
            component.data.get("bias")
            or component.data.get("current_bias")
            or component.data.get("sentiment")
        )
        parsed = _direction(candidate)
        if parsed:
            directions.append(parsed)
    if len(directions) < 2:
        return 0.5, 0.0
    majority = max(directions.count(1), directions.count(-1))
    agreement = majority / len(directions)
    conflict = 1.0 - agreement if 1 in directions and -1 in directions else 0.0
    return round(agreement, 4), round(conflict, 4)


def scenario_dominance(pack: ResearchPack) -> float:
    technical = pack.component("technical")
    scenarios = technical.data.get("scenarios") if technical and technical.available else None
    if not isinstance(scenarios, (list, tuple)) or not scenarios:
        return 0.5
    weights = sorted(
        (float(item.get("weight") or 0) for item in scenarios if isinstance(item, dict)),
        reverse=True,
    )
    if not weights:
        return 0.5
    gap = weights[0] - (weights[1] if len(weights) > 1 else 0.0)
    return round(min(1.0, max(0.0, (weights[0] + gap) / 100.0)), 4)


def freshness_score(pack: ResearchPack) -> float:
    available = [item for item in pack.components if item.available]
    if not available:
        return 0.0
    values = {
        "CURRENT": 1.0,
        "LATEST_AVAILABLE": 0.9,
        "RECENT": 0.85,
        "STALE": 0.45,
    }
    return round(
        sum(values.get(item.freshness.upper(), 0.7) for item in available) / len(available),
        4,
    )


def risk_penalty(risk_outputs: list[dict[str, Any]]) -> float:
    values = {"LOW": 0.1, "MEDIUM": 0.35, "HIGH": 0.7, "VERY HIGH": 1.0}
    if not risk_outputs:
        return 0.5
    return round(
        sum(values.get(str(item.get("risk_level") or "").upper(), 0.5) for item in risk_outputs)
        / len(risk_outputs),
        4,
    )


def deterministic_confidence(
    *,
    coverage: float,
    agreement: float,
    dominance: float,
    freshness: float,
    conflict: float,
    risk: float,
    weights: Mapping[str, float],
) -> int:
    factors = {
        "coverage": coverage,
        "agreement": agreement,
        "scenario_dominance": dominance,
        "freshness": freshness,
        "inverse_conflict": 1.0 - conflict,
        "inverse_risk": 1.0 - risk,
    }
    total = sum(float(weights.get(name, 0.0)) for name in factors) or 1.0
    score = sum(float(weights.get(name, 0.0)) * value for name, value in factors.items()) / total
    return max(0, min(100, round(score * 100)))
