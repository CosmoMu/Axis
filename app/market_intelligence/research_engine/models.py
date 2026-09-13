"""Immutable structured models for the AXIS research graph."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ResearchComponent:
    component: str
    status: str
    provider: str
    as_of: datetime
    source_timestamp: datetime | None
    retrieval_timestamp: datetime
    freshness: str
    coverage: float
    data: dict[str, Any]
    warnings: tuple[str, ...] = ()
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.retrieval_timestamp.tzinfo is None:
            raise ValueError("research timestamps must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.tzinfo is None:
            raise ValueError("source_timestamp must be timezone-aware")
        if not 0 <= self.coverage <= 1:
            raise ValueError("component coverage must be between 0 and 1")

    @property
    def available(self) -> bool:
        return self.status == "AVAILABLE"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("as_of", "source_timestamp", "retrieval_timestamp"):
            value = payload[key]
            payload[key] = value.isoformat() if value is not None else None
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True, slots=True)
class ResearchPack:
    ticker: str
    asset_type: str
    as_of: datetime
    policy_version: str
    components: tuple[ResearchComponent, ...]
    memory: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        names = [item.component for item in self.components]
        if len(names) != len(set(names)):
            raise ValueError("research component names must be unique")

    def component(self, name: str) -> ResearchComponent | None:
        return next((item for item in self.components if item.component == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "as_of": self.as_of.isoformat(),
            "policy_version": self.policy_version,
            "components": [item.to_dict() for item in self.components],
            "memory": list(self.memory),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AgentOutput:
    agent_type: str
    status: str
    structured_output: dict[str, Any]
    provider: str | None
    model: str | None
    workload: str | None
    prompt_version: str | None
    schema_version: str | None
    source_timestamp: datetime | None
    latency_ms: int
    error_type: str | None = None
    response_id: str | None = None
    input_pack_fingerprint: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.source_timestamp is not None:
            payload["source_timestamp"] = self.source_timestamp.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class AxisResearchView:
    ticker: str
    as_of: datetime
    research_stance: str | None
    research_confidence: int
    market_structure: str
    gamma_context: str
    fundamental_context: str
    news_context: str
    sentiment_context: str
    bull_case: str
    bear_case: str
    primary_scenario: str
    alternate_scenario: str
    price: float | None
    key_support: tuple[float, ...]
    key_resistance: tuple[float, ...]
    bullish_trigger: float | None
    bearish_trigger: float | None
    invalidation: float | None
    targets: tuple[float, ...]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    time_horizon: str
    coverage_score: float
    agreement_score: float
    scenario_dominance: float
    freshness_score: float
    conflict_penalty: float
    risk_penalty: float
    warnings: tuple[str, ...]
    component_ids: tuple[str, ...]
    policy_version: str
    generated_at: datetime
    insufficient_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ResearchRunResult:
    run_id: uuid.UUID
    view: AxisResearchView
    pack: ResearchPack
    agent_outputs: tuple[AgentOutput, ...]
    stock_chart_png: bytes | None
    gex_chart_png: bytes | None
    cache_hit: bool
    latency_ms: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    provider_calls: int
