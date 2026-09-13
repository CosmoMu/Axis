# AXIS Multi-Agent Research

**Phase:** `AXIS MULTI-AGENT RESEARCH = TEST ONLY`

**Policy:** `AXIS_RESEARCH_V1`

## Scope and safety boundary

`/research ticker:TICKER` is a read-only market-research workflow. Phase 1 is restricted at both
Discord and runtime layers to the configured Owner, exact AXIS Guild, and `🧪・卡片测试` channel.
It must not create a Signal, Trade, Results candidate, Membership change, Stripe action, Personal
Execution change, or broker order. Member Lounge launch remains disabled until the Owner sends the
exact future approval `APPROVE RESEARCH LOUNGE LAUNCH`.

Kill switch and mode:

- `AXIS_RESEARCH_ENABLED`
- `AXIS_RESEARCH_MODE=TEST`
- `AXIS_RESEARCH_POLICY=config/research_engine.yaml`
- any enabled mode other than `TEST` fails startup closed

Rollback is operational: set `AXIS_RESEARCH_ENABLED=false`, deploy/restart, and confirm `/research`
is absent. The forward-only database tables may remain; rollback does not delete research history.

## Upstream architecture review

The design review used TauricResearch TradingAgents `v0.4.0`, commit `2448d0a`, under Apache-2.0.
AXIS adapted the public architectural ideas—specialized analysts, Bull/Bear debate, research
manager, risk perspectives, and outcome memory. No upstream runtime, graph, prompt, or source file
is vendored or imported. Attribution is recorded in `docs/third_party/TRADINGAGENTS_NOTICE.md`.

## AXIS-native graph

```text
one canonical as_of
        ↓
parallel provider collection
Stock Analyst + GEX + Fundamentals + News/Macro + Sentiment
        ↓
immutable, fingerprinted ResearchPack
        ↓
Bull ∥ Bear → Research Manager → Aggressive ∥ Neutral ∥ Conservative Risk
        ↓
structured AXIS synthesis
        ↓
deterministic coverage + confidence + provider-owned numeric levels
        ↓
AxisResearchView + stock chart + owner-only detail controls
```

The Technical component calls the existing `StockAnalystQueryService`; its levels and stock chart
are reused unchanged. The GEX component calls the existing `GexExplorerService`; its structured
levels and heatmap are reused unchanged. Research contains no duplicate technical or GEX engine.
Massive remains the formal provider boundary. Existing GEX Moomoo intraday shadow behavior remains
read-only and is not selected as Research truth; Research has no broker/execution integration.

## Provider and point-in-time rules

- One UTC `as_of` is created before collection and stored on the run and every component.
- Technical/GEX reject a source timestamp after `as_of` beyond the small transport tolerance.
- News uses `published_utc <= as_of` and treats article text as untrusted data.
- Fundamentals use only filings/periods dated on or before `as_of`; raw metrics retain provider,
  filing timestamp, retrieval timestamp, and value.
- Memory loads only reflections whose `resolution_timestamp <= as_of`.
- Missing data stays unavailable or `—`; it is never converted into fabricated zeroes.

## Coverage and confidence

Configured component weights are Technical 30%, GEX 20%, Fundamentals 20%, News/Macro 20%, and
Sentiment 10%. `NOT_APPLICABLE` components are removed from the denominator. A run requires
Technical plus at least two available optional components; otherwise it persists an insufficient
data view and makes zero LLM calls.

Final confidence is deterministic and bounded to 0–100:

```text
25% coverage
+ 20% Bull/Bear agreement
+ 20% scenario dominance
+ 15% freshness
+ 10% inverse conflict
+ 10% inverse risk
```

The LLM cannot override this score. Missing coverage, stale evidence, disagreement, conflicts, and
risk reduce it. Research stance is `BULLISH`, `BEARISH`, or `NEUTRAL`; it is not a trade command.

## LLM workloads and integrity

All calls use the existing OpenAI Responses `ModelRouter` with strict JSON Schema:

- `RESEARCH_BULL`, `RESEARCH_BEAR`
- `RESEARCH_MANAGER`
- `RESEARCH_RISK_AGGRESSIVE`, `RESEARCH_RISK_NEUTRAL`, `RESEARCH_RISK_CONSERVATIVE`
- `RESEARCH_SYNTHESIS`
- `RESEARCH_REFLECTION` is reserved for a future controlled reflection route; V1 outcome lessons
  are deterministic and do not add another live call

Agents receive the same frozen pack fingerprint, have no tools, cannot fetch after freeze, and are
told that external text is data rather than instructions. Strict schema validation is mandatory.
Numeric post-processing removes a number that is absent from the frozen provider input. Final spot,
support, resistance, triggers, targets, and invalidation are copied only from deterministic
Technical/GEX fields, never from prose generation. No chain-of-thought is requested or stored.

## Runtime controls

- total run timeout: 120 seconds
- per-agent timeout: 45 seconds
- maximum LLM calls: 7; maximum debate rounds: 1
- cache: 300 seconds; key includes ticker, as-of bucket, policy, Stock/GEX versions, and providers
- same-key requests: single-flight
- ordinary configured user cooldown: 30 seconds
- fresh Guild limit: 6/minute; concurrent runs: 2
- provider request timeout: 15 seconds
- one original Discord progress message is edited through stages and replaced by the final card

Owner-only ephemeral detail buttons expose Technical, GEX, Fundamentals, News, Bull vs Bear, and
Risk structured evidence. Provider/LLM failures are classified, audited, deduplicated in System
Alerts, and followed by Recovery when healthy again. Partial failure may continue only while the
minimum coverage gate remains satisfied.

## Persistence, outcomes, and memory

Migration `20260913_0033` creates `research_runs`, `research_agent_outputs`, `research_outcomes`, and
`research_reflections`. Runs retain policy, timestamps, frozen pack/fingerprint, component status,
structured outputs, deterministic score inputs, latency, usage, and safe error types. They do not
store chain-of-thought or Secret values.

Completed views seed pending 1/3/5 US-trading-session outcomes. The hourly resolver waits until the
target session closes, then records underlying return, SPY benchmark return, alpha, MFE, MAE,
target/invalidation outcome, and resolution timestamp. Only resolved lessons are eligible for later
packs: at most three same-ticker and two cross-ticker lessons, always cut off at the new run's
`as_of`. Restart safety comes from database status and uniqueness constraints.

## Operations and validation

```bash
.venv/bin/python scripts/verify_research_engine.py
.venv/bin/python scripts/validate_multi_agent_research.py SPY QQQ NVDA TSLA AAPL
.venv/bin/pytest -q tests/test_multi_agent_research.py
```

The E2E script outputs only status, coverage, confidence, component error codes, latency, call count,
and token counts. Massive throttling is a valid insufficient-data result and must never be bypassed
with invented or stale evidence. If repeated throttling occurs, wait for provider recovery or turn
off the isolated Research kill switch; do not weaken the coverage gate.

## Future Member Lounge launch

Not part of Phase 1. Before a future launch, revalidate live Massive capacity, cold/cache latency,
Discord desktop/mobile detail UX, member rate limits, alert recovery, cost, and all strict
no-side-effect assertions. The code intentionally rejects `MEMBER_LOUNGE` mode today.
