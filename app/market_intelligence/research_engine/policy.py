"""Versioned configuration for AXIS Multi-Agent Research."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ResearchPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResearchPolicy:
    version: str
    total_timeout_seconds: int
    agent_timeout_seconds: int
    max_llm_calls: int
    max_debate_rounds: int
    cache_seconds: int
    user_cooldown_seconds: int
    ticker_cooldown_seconds: int
    guild_fresh_limit_per_minute: int
    max_concurrent_runs: int
    as_of_bucket_seconds: int
    minimum_optional_components: int
    coverage_weights: dict[str, float]
    confidence_weights: dict[str, float]
    same_ticker_memory_limit: int
    cross_ticker_memory_limit: int
    outcome_horizons: tuple[int, ...]
    provider_timeout_seconds: int
    max_news_items: int
    max_source_text_chars: int
    benchmark_ticker: str

    @classmethod
    def load(cls, path: Path, *, version_override: str | None = None) -> ResearchPolicy:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            runtime = raw["runtime"]
            coverage = raw["coverage"]
            confidence = raw["confidence"]
            memory = raw["memory"]
            providers = raw["providers"]
            policy = cls(
                version=version_override or str(raw["version"]),
                total_timeout_seconds=int(runtime["total_timeout_seconds"]),
                agent_timeout_seconds=int(runtime["agent_timeout_seconds"]),
                max_llm_calls=int(runtime["max_llm_calls"]),
                max_debate_rounds=int(runtime["max_debate_rounds"]),
                cache_seconds=int(runtime["cache_seconds"]),
                user_cooldown_seconds=int(runtime["user_cooldown_seconds"]),
                ticker_cooldown_seconds=int(runtime["ticker_cooldown_seconds"]),
                guild_fresh_limit_per_minute=int(runtime["guild_fresh_limit_per_minute"]),
                max_concurrent_runs=int(runtime["max_concurrent_runs"]),
                as_of_bucket_seconds=int(runtime["as_of_bucket_seconds"]),
                minimum_optional_components=int(coverage["minimum_optional_components"]),
                coverage_weights={
                    str(key): float(value) for key, value in coverage["component_weights"].items()
                },
                confidence_weights={
                    str(key): float(value) for key, value in confidence["weights"].items()
                },
                same_ticker_memory_limit=int(memory["same_ticker_limit"]),
                cross_ticker_memory_limit=int(memory["cross_ticker_limit"]),
                outcome_horizons=tuple(int(value) for value in memory["outcome_horizons"]),
                provider_timeout_seconds=int(providers["request_timeout_seconds"]),
                max_news_items=int(providers["max_news_items"]),
                max_source_text_chars=int(providers["max_source_text_chars"]),
                benchmark_ticker=str(providers["benchmark_ticker"]).upper(),
            )
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID") from exc
        policy.validate()
        return policy

    def validate(self) -> None:
        positive = (
            self.total_timeout_seconds,
            self.agent_timeout_seconds,
            self.max_llm_calls,
            self.max_debate_rounds,
            self.cache_seconds,
            self.user_cooldown_seconds,
            self.ticker_cooldown_seconds,
            self.guild_fresh_limit_per_minute,
            self.max_concurrent_runs,
            self.as_of_bucket_seconds,
            self.provider_timeout_seconds,
            self.max_news_items,
            self.max_source_text_chars,
        )
        if any(value <= 0 for value in positive):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
        if self.minimum_optional_components not in range(1, 5):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
        if sorted(set(self.outcome_horizons)) != list(self.outcome_horizons):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
        if any(value <= 0 for value in self.outcome_horizons):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
        if self.max_llm_calls < (2 * self.max_debate_rounds) + 5:
            raise ResearchPolicyError("RESEARCH_POLICY_LLM_BUDGET_TOO_LOW")
        expected_coverage = {"technical", "gex", "fundamentals", "news_macro", "sentiment"}
        if set(self.coverage_weights) != expected_coverage or not all(
            value >= 0 for value in self.coverage_weights.values()
        ):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
        expected_confidence = {
            "coverage",
            "agreement",
            "scenario_dominance",
            "freshness",
            "inverse_conflict",
            "inverse_risk",
        }
        if set(self.confidence_weights) != expected_confidence or not all(
            value >= 0 for value in self.confidence_weights.values()
        ):
            raise ResearchPolicyError("RESEARCH_POLICY_INVALID")
