"""AXIS-native multi-agent research orchestration and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.db.models import AuditLog, ResearchAgentOutput, ResearchRun
from app.db.session import Database
from app.domain.enums import LlmWorkload
from app.market_intelligence.research_engine.agents.llm import (
    ResearchAgentError,
    ResearchAgentRunner,
)
from app.market_intelligence.research_engine.confidence import (
    agreement_and_conflict,
    deterministic_confidence,
    freshness_score,
    risk_penalty,
    scenario_dominance,
)
from app.market_intelligence.research_engine.coverage import (
    coverage_score,
    minimum_coverage_met,
)
from app.market_intelligence.research_engine.memory import ResearchMemoryStore
from app.market_intelligence.research_engine.models import (
    AgentOutput,
    AxisResearchView,
    ResearchComponent,
    ResearchPack,
    ResearchRunResult,
)
from app.market_intelligence.research_engine.outcomes import ResearchOutcomeService
from app.market_intelligence.research_engine.policy import ResearchPolicy
from app.market_intelligence.research_engine.providers.axis import CollectedComponent
from app.services.stock_analyst import StockAnalystError, normalize_stock_ticker

ProgressCallback = Callable[[str, str], Awaitable[None]]


class ResearchError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    created_monotonic: float
    result: ResearchRunResult


def _unavailable(name: str, as_of: datetime, code: str) -> ResearchComponent:
    return ResearchComponent(
        component=name,
        status="UNAVAILABLE",
        provider="unavailable",
        as_of=as_of,
        source_timestamp=None,
        retrieval_timestamp=datetime.now(UTC),
        freshness="UNAVAILABLE",
        coverage=0.0,
        data={},
        warnings=(code,),
        error_type=code,
    )


def _error_code(exc: BaseException, fallback: str) -> str:
    value = getattr(exc, "code", None)
    return str(value) if value else fallback


def _numeric_list(value: Any, *, limit: int = 4) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        float(item)
        for item in value[:limit]
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    )


class ResearchService:
    """Read-only market research; never imports or calls execution/publication services."""

    def __init__(
        self,
        database: Database,
        *,
        policy: ResearchPolicy,
        technical_provider: Any,
        gex_provider: Any,
        fundamentals_provider: Any,
        news_provider: Any,
        sentiment_provider: Any,
        agents: ResearchAgentRunner,
        memory: ResearchMemoryStore,
        outcomes: ResearchOutcomeService | None = None,
    ) -> None:
        self.database = database
        self.policy = policy
        self.technical_provider = technical_provider
        self.gex_provider = gex_provider
        self.fundamentals_provider = fundamentals_provider
        self.news_provider = news_provider
        self.sentiment_provider = sentiment_provider
        self.agents = agents
        self.memory = memory
        self.outcomes = outcomes
        self._cache: dict[str, _CacheEntry] = {}
        self._inflight: dict[str, asyncio.Task[ResearchRunResult]] = {}
        self._last_user_request: dict[tuple[int, int], float] = {}
        self._last_ticker_request: dict[tuple[int, str], float] = {}
        self._guild_fresh_requests: defaultdict[int, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(policy.max_concurrent_runs)

    @property
    def provider_signature(self) -> str:
        names = (
            getattr(self.technical_provider, "name", "technical"),
            getattr(self.gex_provider, "name", "gex"),
            getattr(self.fundamentals_provider, "name", "fundamentals"),
            getattr(self.news_provider, "name", "news"),
            getattr(self.sentiment_provider, "name", "sentiment"),
        )
        return "+".join(names)

    def cache_key(self, ticker: str, as_of: datetime) -> str:
        bucket = int(as_of.timestamp()) // self.policy.as_of_bucket_seconds
        raw = "|".join(
            (
                ticker,
                str(bucket),
                self.policy.version,
                str(getattr(self.technical_provider, "version", "unknown")),
                str(getattr(self.gex_provider, "version", "unknown")),
                self.provider_signature,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    async def query(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None = None,
        as_of: datetime | None = None,
        progress: ProgressCallback | None = None,
        enforce_rate_limits: bool = True,
        bypass_cooldowns: bool = False,
    ) -> ResearchRunResult:
        try:
            symbol = normalize_stock_ticker(ticker)
        except StockAnalystError as exc:
            raise ResearchError("RESEARCH_TICKER_INVALID") from exc
        requested_at = (as_of or datetime.now(UTC)).astimezone(UTC)
        key = self.cache_key(symbol, requested_at)
        started = time.monotonic()
        await self._audit(
            "RESEARCH_REQUESTED",
            guild_id,
            actor_user_id,
            symbol,
            interaction_id,
            {"as_of": requested_at.isoformat(), "policy_version": self.policy.version},
        )
        now = time.monotonic()
        leader = False
        task: asyncio.Task[ResearchRunResult] | None = None
        cached: ResearchRunResult | None = None
        async with self._lock:
            if enforce_rate_limits and not bypass_cooldowns:
                user_key = (guild_id, actor_user_id)
                previous = self._last_user_request.get(user_key)
                if previous is not None and now - previous < self.policy.user_cooldown_seconds:
                    await self._rate_limited(
                        guild_id, actor_user_id, symbol, interaction_id, "USER_COOLDOWN"
                    )
                    raise ResearchError("RESEARCH_USER_COOLDOWN")
                ticker_key = (guild_id, symbol)
                previous_ticker = self._last_ticker_request.get(ticker_key)
                if (
                    previous_ticker is not None
                    and now - previous_ticker < self.policy.ticker_cooldown_seconds
                ):
                    await self._rate_limited(
                        guild_id, actor_user_id, symbol, interaction_id, "TICKER_COOLDOWN"
                    )
                    raise ResearchError("RESEARCH_TICKER_COOLDOWN")
                self._last_user_request[user_key] = now
                self._last_ticker_request[ticker_key] = now
            cache_entry = self._cache.get(key)
            if (
                cache_entry is not None
                and now - cache_entry.created_monotonic <= self.policy.cache_seconds
            ):
                cached = replace(
                    cache_entry.result,
                    cache_hit=True,
                    latency_ms=max(0, round((time.monotonic() - started) * 1000)),
                )
            else:
                task = self._inflight.get(key)
                if task is None:
                    if enforce_rate_limits:
                        recent = self._guild_fresh_requests[guild_id]
                        while recent and now - recent[0] >= 60:
                            recent.popleft()
                        if len(recent) >= self.policy.guild_fresh_limit_per_minute:
                            await self._rate_limited(
                                guild_id,
                                actor_user_id,
                                symbol,
                                interaction_id,
                                "GUILD_FRESH_LIMIT",
                            )
                            raise ResearchError("RESEARCH_GUILD_RATE_LIMIT")
                        recent.append(now)
                    task = asyncio.create_task(
                        self._generate(
                            guild_id=guild_id,
                            actor_user_id=actor_user_id,
                            ticker=symbol,
                            interaction_id=interaction_id,
                            as_of=requested_at,
                            cache_key=key,
                            progress=progress,
                        )
                    )
                    self._inflight[key] = task
                    task.add_done_callback(
                        lambda completed, cache_key=key: asyncio.create_task(
                            self._clear_inflight(cache_key, completed)
                        )
                    )
                    leader = True
        if cached is not None:
            await self._audit(
                "RESEARCH_CACHE_HIT",
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                {"run_id": str(cached.run_id), "cache_key": key},
            )
            return cached
        await self._audit(
            "RESEARCH_CACHE_MISS",
            guild_id,
            actor_user_id,
            symbol,
            interaction_id,
            {"cache_key": key},
        )
        assert task is not None
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), timeout=self.policy.total_timeout_seconds
            )
            if leader:
                async with self._lock:
                    self._cache[key] = _CacheEntry(time.monotonic(), result)
            return replace(
                result,
                cache_hit=False,
                latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            )
        except TimeoutError as exc:
            await self._audit(
                "RESEARCH_FAILED",
                guild_id,
                actor_user_id,
                symbol,
                interaction_id,
                {"error_type": "RESEARCH_TIMEOUT"},
            )
            raise ResearchError("RESEARCH_TIMEOUT") from exc
    async def _clear_inflight(
        self, key: str, task: asyncio.Task[ResearchRunResult]
    ) -> None:
        async with self._lock:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _generate(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        as_of: datetime,
        cache_key: str,
        progress: ProgressCallback | None,
    ) -> ResearchRunResult:
        started = time.monotonic()
        run_id = uuid.uuid4()
        await self._create_run(run_id, guild_id, actor_user_id, ticker, as_of, cache_key)
        await self._audit(
            "RESEARCH_STARTED",
            guild_id,
            actor_user_id,
            ticker,
            interaction_id,
            {"run_id": str(run_id), "as_of": as_of.isoformat()},
        )
        try:
            async with self._semaphore:
                memory = await self.memory.load(
                    ticker=ticker,
                    as_of=as_of,
                    same_ticker_limit=self.policy.same_ticker_memory_limit,
                    cross_ticker_limit=self.policy.cross_ticker_memory_limit,
                )
                collected = await self._collect_components(
                    guild_id, actor_user_id, ticker, as_of, progress
                )
                components = tuple(item.component for item in collected)
                fundamentals = next(item for item in components if item.component == "fundamentals")
                asset_type = str(fundamentals.data.get("asset_type") or "UNKNOWN")
                pack = ResearchPack(
                    ticker=ticker,
                    asset_type=asset_type,
                    as_of=as_of,
                    policy_version=self.policy.version,
                    components=components,
                    memory=memory,
                )
                stock_chart = next(
                    (
                        item.chart_png
                        for item in collected
                        if item.component.component == "technical"
                    ),
                    None,
                )
                gex_chart = next(
                    (item.chart_png for item in collected if item.component.component == "gex"),
                    None,
                )
                component_outputs = tuple(self._component_output(item, pack) for item in components)
                coverage = coverage_score(pack, self.policy.coverage_weights)
                if not minimum_coverage_met(pack, self.policy.minimum_optional_components):
                    view = self._insufficient_view(pack, coverage)
                    await self._complete_run(
                        run_id,
                        status="INSUFFICIENT_DATA",
                        pack=pack,
                        view=view,
                        outputs=component_outputs,
                        latency_ms=round((time.monotonic() - started) * 1000),
                        provider_calls=5,
                        error_type="RESEARCH_MIN_COVERAGE_FAILURE",
                    )
                    await self._audit(
                        "RESEARCH_FAILED",
                        guild_id,
                        actor_user_id,
                        ticker,
                        interaction_id,
                        {
                            "run_id": str(run_id),
                            "coverage": coverage,
                            "error_type": "RESEARCH_MIN_COVERAGE_FAILURE",
                        },
                    )
                    return ResearchRunResult(
                        run_id,
                        view,
                        pack,
                        component_outputs,
                        stock_chart,
                        gex_chart,
                        False,
                        round((time.monotonic() - started) * 1000),
                        0,
                        0,
                        0,
                        5,
                    )
                reasoning_outputs = await self._reason(pack, progress)
                all_outputs = (*component_outputs, *reasoning_outputs)
                view = self._final_view(pack, list(reasoning_outputs), coverage)
                partial = any(item.status != "AVAILABLE" for item in components)
                status = "PARTIAL" if partial else "COMPLETED"
                llm_calls = len(reasoning_outputs)
                input_tokens = sum(item.input_tokens or 0 for item in reasoning_outputs)
                output_tokens = sum(item.output_tokens or 0 for item in reasoning_outputs)
                latency_ms = round((time.monotonic() - started) * 1000)
                await self._complete_run(
                    run_id,
                    status=status,
                    pack=pack,
                    view=view,
                    outputs=all_outputs,
                    latency_ms=latency_ms,
                    provider_calls=5,
                    llm_calls=llm_calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if self.outcomes is not None:
                    await self.outcomes.seed(run_id, as_of=as_of)
                await self._audit(
                    "RESEARCH_PARTIAL" if partial else "RESEARCH_COMPLETED",
                    guild_id,
                    actor_user_id,
                    ticker,
                    interaction_id,
                    {
                        "run_id": str(run_id),
                        "coverage": coverage,
                        "stance": view.research_stance,
                        "confidence": view.research_confidence,
                        "latency_ms": latency_ms,
                        "agent_statuses": {item.agent_type: item.status for item in all_outputs},
                        "llm_usage": {
                            item.agent_type: {
                                "provider": item.provider,
                                "model": item.model,
                                "workload": item.workload,
                            }
                            for item in reasoning_outputs
                        },
                        "policy_version": self.policy.version,
                    },
                )
                return ResearchRunResult(
                    run_id,
                    view,
                    pack,
                    tuple(all_outputs),
                    stock_chart,
                    gex_chart,
                    False,
                    latency_ms,
                    llm_calls,
                    input_tokens,
                    output_tokens,
                    5,
                )
        except ResearchError:
            raise
        except Exception as exc:
            code = _error_code(exc, "RESEARCH_FAILED")
            await self._fail_run(run_id, code, round((time.monotonic() - started) * 1000))
            await self._audit(
                "RESEARCH_FAILED",
                guild_id,
                actor_user_id,
                ticker,
                interaction_id,
                {"run_id": str(run_id), "error_type": code},
            )
            raise ResearchError(code) from exc

    async def _collect_components(
        self,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        as_of: datetime,
        progress: ProgressCallback | None,
    ) -> tuple[CollectedComponent, ...]:
        specs: tuple[tuple[str, Callable[[], Awaitable[Any]], str], ...] = (
            (
                "technical",
                lambda: self.technical_provider.fetch(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    ticker=ticker,
                    as_of=as_of,
                ),
                "RESEARCH_TECHNICAL_FAILURE",
            ),
            (
                "gex",
                lambda: self.gex_provider.fetch(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    ticker=ticker,
                    as_of=as_of,
                ),
                "RESEARCH_GEX_FAILURE",
            ),
            (
                "fundamentals",
                lambda: self.fundamentals_provider.fetch(ticker, as_of=as_of),
                "RESEARCH_FUNDAMENTALS_FAILURE",
            ),
            (
                "news_macro",
                lambda: self.news_provider.fetch(ticker, as_of=as_of),
                "RESEARCH_NEWS_FAILURE",
            ),
            (
                "sentiment",
                lambda: self.sentiment_provider.fetch(ticker, as_of=as_of),
                "RESEARCH_SENTIMENT_FAILURE",
            ),
        )

        async def collect(
            name: str, awaitable: Awaitable[Any], fallback: str
        ) -> CollectedComponent:
            if progress is not None:
                await progress(name, "RUNNING")
            try:
                value = await asyncio.wait_for(awaitable, timeout=self.policy.agent_timeout_seconds)
                result = (
                    value if isinstance(value, CollectedComponent) else CollectedComponent(value)
                )
                if progress is not None:
                    await progress(name, "DONE" if result.component.available else "UNAVAILABLE")
                return result
            except Exception as exc:
                code = _error_code(exc, fallback)
                if progress is not None:
                    await progress(name, "FAILED")
                return CollectedComponent(_unavailable(name, as_of, code))

        collected = []
        for name, factory, fallback in specs:
            collected.append(await collect(name, factory(), fallback))
        return tuple(collected)

    async def _reason(
        self, pack: ResearchPack, progress: ProgressCallback | None
    ) -> tuple[AgentOutput, ...]:
        outputs: list[AgentOutput] = []
        debate_context: dict[str, Any] = {}
        for _ in range(self.policy.max_debate_rounds):
            if progress is not None:
                await progress("bull_bear", "RUNNING")
            bull, bear = await asyncio.gather(
                self._run_agent(LlmWorkload.RESEARCH_BULL, pack, debate_context),
                self._run_agent(LlmWorkload.RESEARCH_BEAR, pack, debate_context),
            )
            outputs.extend((bull, bear))
            debate_context = {"bull": bull.structured_output, "bear": bear.structured_output}
        if progress is not None:
            await progress("bull_bear", "DONE")
            await progress("manager", "RUNNING")
        manager = await self._run_agent(LlmWorkload.RESEARCH_MANAGER, pack, debate_context)
        outputs.append(manager)
        if progress is not None:
            await progress("manager", "DONE")
            await progress("risk", "RUNNING")
        risk_context = {"manager": manager.structured_output, **debate_context}
        risks = await asyncio.gather(
            self._run_agent(LlmWorkload.RESEARCH_RISK_AGGRESSIVE, pack, risk_context),
            self._run_agent(LlmWorkload.RESEARCH_RISK_NEUTRAL, pack, risk_context),
            self._run_agent(LlmWorkload.RESEARCH_RISK_CONSERVATIVE, pack, risk_context),
        )
        outputs.extend(risks)
        if progress is not None:
            await progress("risk", "DONE")
            await progress("synthesis", "RUNNING")
        synthesis = await self._run_agent(
            LlmWorkload.RESEARCH_SYNTHESIS,
            pack,
            {
                **risk_context,
                "risk_reviews": [item.structured_output for item in risks],
            },
        )
        outputs.append(synthesis)
        if len(outputs) > self.policy.max_llm_calls:
            raise ResearchError("RESEARCH_LLM_CALL_BUDGET_EXCEEDED")
        if progress is not None:
            await progress("synthesis", "DONE")
        return tuple(outputs)

    async def _run_agent(
        self,
        workload: LlmWorkload,
        pack: ResearchPack,
        context: dict[str, Any],
    ) -> AgentOutput:
        try:
            return await asyncio.wait_for(
                self.agents.run(workload, pack=pack, context=context),
                timeout=self.policy.agent_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ResearchError("RESEARCH_TIMEOUT") from exc
        except ResearchAgentError as exc:
            raise ResearchError(exc.code) from exc

    def _final_view(
        self,
        pack: ResearchPack,
        outputs: list[AgentOutput],
        coverage: float,
    ) -> AxisResearchView:
        by_type = {item.agent_type: item.structured_output for item in outputs}
        manager = by_type[LlmWorkload.RESEARCH_MANAGER.value]
        synthesis = by_type[LlmWorkload.RESEARCH_SYNTHESIS.value]
        risk_rows = [
            by_type[item.value]
            for item in (
                LlmWorkload.RESEARCH_RISK_AGGRESSIVE,
                LlmWorkload.RESEARCH_RISK_NEUTRAL,
                LlmWorkload.RESEARCH_RISK_CONSERVATIVE,
            )
        ]
        agreement, conflict = agreement_and_conflict(pack)
        dominance = scenario_dominance(pack)
        freshness = freshness_score(pack)
        risk = risk_penalty(risk_rows)
        confidence = deterministic_confidence(
            coverage=coverage,
            agreement=agreement,
            dominance=dominance,
            freshness=freshness,
            conflict=conflict,
            risk=risk,
            weights=self.policy.confidence_weights,
        )
        technical = pack.component("technical")
        gex = pack.component("gex")
        technical_data = technical.data if technical and technical.available else {}
        gex_data = gex.data if gex and gex.available else {}
        supports = _numeric_list(technical_data.get("support_levels"), limit=3)
        supports += _numeric_list(gex_data.get("major_support"), limit=2)
        resistance = _numeric_list(technical_data.get("resistance_levels"), limit=3)
        resistance += _numeric_list(gex_data.get("major_resistance"), limit=2)
        warnings = tuple(
            dict.fromkeys(
                warning for component in pack.components for warning in component.warnings
            )
        )
        return AxisResearchView(
            ticker=pack.ticker,
            as_of=pack.as_of,
            research_stance=str(manager.get("research_stance") or "NEUTRAL"),
            research_confidence=confidence,
            market_structure=str(synthesis.get("market_structure") or "数据不足"),
            gamma_context=str(synthesis.get("gamma_context") or "不可用"),
            fundamental_context=str(synthesis.get("fundamental_context") or "不可用"),
            news_context=str(synthesis.get("news_context") or "不可用"),
            sentiment_context=str(synthesis.get("sentiment_context") or "不可用"),
            bull_case=str(synthesis.get("bull_case") or "不可用"),
            bear_case=str(synthesis.get("bear_case") or "不可用"),
            primary_scenario=str(synthesis.get("primary_scenario") or "不可用"),
            alternate_scenario=str(synthesis.get("alternate_scenario") or "不可用"),
            price=(
                float(technical_data["price"])
                if isinstance(technical_data.get("price"), (int, float))
                else float(gex_data["spot"])
                if isinstance(gex_data.get("spot"), (int, float))
                else None
            ),
            key_support=tuple(dict.fromkeys(supports)),
            key_resistance=tuple(dict.fromkeys(resistance)),
            bullish_trigger=(
                float(gex_data["bullish_trigger"])
                if isinstance(gex_data.get("bullish_trigger"), (int, float))
                else resistance[0]
                if resistance
                else None
            ),
            bearish_trigger=(
                float(gex_data["bearish_trigger"])
                if isinstance(gex_data.get("bearish_trigger"), (int, float))
                else supports[0]
                if supports
                else None
            ),
            invalidation=(
                float(technical_data["invalidation"])
                if isinstance(technical_data.get("invalidation"), (int, float))
                else None
            ),
            targets=_numeric_list(technical_data.get("targets"), limit=4),
            catalysts=tuple(str(item) for item in synthesis.get("catalysts", [])[:5]),
            risks=tuple(str(item) for item in synthesis.get("risks", [])[:6]),
            time_horizon=str(synthesis.get("time_horizon") or "MIXED"),
            coverage_score=coverage,
            agreement_score=agreement,
            scenario_dominance=dominance,
            freshness_score=freshness,
            conflict_penalty=conflict,
            risk_penalty=risk,
            warnings=warnings,
            component_ids=tuple(
                f"{item.component}:{pack.fingerprint[:12]}" for item in pack.components
            ),
            policy_version=self.policy.version,
            generated_at=datetime.now(UTC),
        )

    def _insufficient_view(self, pack: ResearchPack, coverage: float) -> AxisResearchView:
        warnings = tuple(
            dict.fromkeys(
                ["RESEARCH_MIN_COVERAGE_FAILURE"]
                + [warning for item in pack.components for warning in item.warnings]
            )
        )
        return AxisResearchView(
            ticker=pack.ticker,
            as_of=pack.as_of,
            research_stance=None,
            research_confidence=0,
            market_structure="INSUFFICIENT DATA",
            gamma_context="不可用",
            fundamental_context="不可用",
            news_context="不可用",
            sentiment_context="不可用",
            bull_case="未生成",
            bear_case="未生成",
            primary_scenario="未生成",
            alternate_scenario="未生成",
            price=None,
            key_support=(),
            key_resistance=(),
            bullish_trigger=None,
            bearish_trigger=None,
            invalidation=None,
            targets=(),
            catalysts=(),
            risks=(),
            time_horizon="MIXED",
            coverage_score=coverage,
            agreement_score=0.0,
            scenario_dominance=0.0,
            freshness_score=freshness_score(pack),
            conflict_penalty=0.0,
            risk_penalty=1.0,
            warnings=warnings,
            component_ids=tuple(
                f"{item.component}:{pack.fingerprint[:12]}" for item in pack.components
            ),
            policy_version=self.policy.version,
            generated_at=datetime.now(UTC),
            insufficient_data=True,
        )

    @staticmethod
    def _component_output(component: ResearchComponent, pack: ResearchPack) -> AgentOutput:
        return AgentOutput(
            agent_type=component.component,
            status=component.status,
            structured_output=component.to_dict(),
            provider=component.provider,
            model=None,
            workload=None,
            prompt_version=None,
            schema_version=None,
            source_timestamp=component.source_timestamp,
            latency_ms=0,
            error_type=component.error_type,
            input_pack_fingerprint=pack.fingerprint,
        )

    async def _create_run(
        self,
        run_id: uuid.UUID,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        as_of: datetime,
        cache_key: str,
    ) -> None:
        async with self.database.session() as session:
            session.add(
                ResearchRun(
                    id=run_id,
                    guild_id=guild_id,
                    ticker=ticker,
                    asset_type="UNKNOWN",
                    as_of=as_of,
                    status="RUNNING",
                    policy_version=self.policy.version,
                    stock_analyst_version=str(
                        getattr(self.technical_provider, "version", "unknown")
                    ),
                    gex_version=str(getattr(self.gex_provider, "version", "unknown")),
                    created_by_discord_user_id=actor_user_id,
                    cache_key=cache_key,
                )
            )
            await session.commit()

    async def _complete_run(
        self,
        run_id: uuid.UUID,
        *,
        status: str,
        pack: ResearchPack,
        view: AxisResearchView,
        outputs: tuple[AgentOutput, ...],
        latency_ms: int,
        provider_calls: int,
        llm_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_type: str | None = None,
    ) -> None:
        async with self.database.session() as session:
            run = await session.get(ResearchRun, run_id)
            if run is None:
                raise ResearchError("RESEARCH_RUN_NOT_FOUND")
            run.asset_type = pack.asset_type
            run.status = status
            run.research_stance = view.research_stance
            run.research_confidence = view.research_confidence
            run.coverage_score = Decimal(str(view.coverage_score))
            run.agreement_score = Decimal(str(view.agreement_score))
            run.scenario_dominance = Decimal(str(view.scenario_dominance))
            run.primary_scenario_json = {"text": view.primary_scenario}
            run.levels_json = {
                "price": view.price,
                "support": list(view.key_support),
                "resistance": list(view.key_resistance),
                "bullish_trigger": view.bullish_trigger,
                "bearish_trigger": view.bearish_trigger,
                "invalidation": view.invalidation,
                "targets": list(view.targets),
            }
            run.risk_json = {"risk_penalty": view.risk_penalty, "risks": list(view.risks)}
            run.research_pack_json = pack.to_dict()
            run.final_view_json = view.to_dict()
            run.completed_at = datetime.now(UTC)
            run.latency_ms = latency_ms
            run.provider_calls = provider_calls
            run.llm_calls = llm_calls
            run.input_tokens = input_tokens
            run.output_tokens = output_tokens
            run.error_type = error_type
            for output in outputs:
                session.add(
                    ResearchAgentOutput(
                        research_run_id=run_id,
                        agent_type=output.agent_type,
                        status=output.status,
                        structured_output_json=output.structured_output,
                        provider=output.provider,
                        model=output.model,
                        workload=output.workload,
                        prompt_version=output.prompt_version,
                        schema_version=output.schema_version,
                        source_timestamp=output.source_timestamp,
                        latency_ms=output.latency_ms,
                        error_type=output.error_type,
                        response_id=output.response_id,
                        input_pack_fingerprint=output.input_pack_fingerprint,
                        input_tokens=output.input_tokens,
                        output_tokens=output.output_tokens,
                    )
                )
            await session.commit()

    async def _fail_run(self, run_id: uuid.UUID, code: str, latency_ms: int) -> None:
        async with self.database.session() as session:
            run = await session.get(ResearchRun, run_id)
            if run is not None:
                run.status = "FAILED"
                run.completed_at = datetime.now(UTC)
                run.latency_ms = latency_ms
                run.error_type = code
                await session.commit()

    async def _rate_limited(
        self,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        reason: str,
    ) -> None:
        await self._audit(
            "RESEARCH_RATE_LIMITED",
            guild_id,
            actor_user_id,
            ticker,
            interaction_id,
            {"reason": reason},
        )

    async def _audit(
        self,
        event: str,
        guild_id: int,
        actor_user_id: int,
        ticker: str,
        interaction_id: int | None,
        payload: dict[str, Any],
    ) -> None:
        async with self.database.session() as session:
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type=event,
                    entity_type="research_request",
                    entity_id=ticker,
                    before_json=None,
                    after_json=json.loads(json.dumps(payload, default=str)),
                    discord_interaction_id=interaction_id,
                )
            )
            await session.commit()
