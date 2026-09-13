"""Deterministic research coverage and minimum-data policy."""

from __future__ import annotations

from collections.abc import Mapping

from app.market_intelligence.research_engine.models import ResearchPack


def coverage_score(pack: ResearchPack, weights: Mapping[str, float]) -> float:
    applicable = {
        name: weight
        for name, weight in weights.items()
        if not (
            pack.component(name) is not None and pack.component(name).status == "NOT_APPLICABLE"
        )
    }
    total = sum(max(0.0, float(value)) for value in applicable.values()) or 1.0
    score = 0.0
    for name, weight in applicable.items():
        component = pack.component(name)
        if component is not None and component.available:
            score += max(0.0, float(weight)) * component.coverage
    return round(min(1.0, max(0.0, score / total)), 4)


def minimum_coverage_met(pack: ResearchPack, minimum_optional: int) -> bool:
    technical = pack.component("technical")
    if technical is None or not technical.available:
        return False
    optional = ("gex", "fundamentals", "news_macro", "sentiment")
    return sum(
        bool(pack.component(name) and pack.component(name).available) for name in optional
    ) >= (minimum_optional)
