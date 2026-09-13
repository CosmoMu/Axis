# AXIS Multi-Agent Research

**Phase:** `AXIS MULTI-AGENT RESEARCH = MEMBER LOUNGE LIVE`

**Policy:** `AXIS_RESEARCH_V1`

## Scope and safety boundary

`/research ticker:TICKER` is a read-only market-research workflow. It is restricted to Member,
Manager and Owner in the exact AXIS Guild and `🛋️・会员交流`; Owner may also use `🧪・卡片测试`.
It must not create a Signal, Trade, Results candidate, Membership change, Stripe action, Personal
Execution change, or broker order.

Kill switch and mode:

- `AXIS_RESEARCH_ENABLED`
- `AXIS_RESEARCH_MODE=MEMBER_LOUNGE`
- `RESEARCH_AUX_DATA_PROVIDER=moomoo`
- `STANDALONE_RESEARCH_TOOLS_ENABLED=false`
- `AXIS_RESEARCH_POLICY=config/research_engine.yaml`
- enabled mode accepts only `TEST` or `MEMBER_LOUNGE`; any other value fails startup closed

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
bounded provider collection
Stock Analyst + GEX + Fundamentals + News/Macro + Analyst Consensus
        ↓
immutable, fingerprinted ResearchPack
        ↓
Bull ∥ Bear → Research Manager → Aggressive ∥ Neutral ∥ Conservative Risk
        ↓
structured AXIS synthesis
        ↓
deterministic coverage + confidence + provider-owned numeric levels
        ↓
AxisResearchView + one public shared card with controlled in-place page switches
```

The Technical component calls the existing `StockAnalystQueryService`; its levels and stock chart
are reused unchanged. The GEX component calls the existing `GexExplorerService`; its structured
levels and heatmap are reused unchanged. Research contains no duplicate technical or GEX engine.
Moomoo is the production source for all five components: existing Stock/GEX engines plus F10
financial statements, News Search and Analyst Consensus. Massive auxiliary provider code remains
dormant for explicit rollback only. Research has no broker/execution integration. The standalone
`/stock`, `/gex` and `gex TICKER` interfaces are disabled without disabling their internal engines.

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
- ordinary member user cooldown: 30 seconds
- same ticker cooldown across the Guild: 60 seconds
- Manager/administrator/Owner bypass both member cooldowns
- fresh Guild limit: 6/minute; concurrent runs: 2
- provider request timeout: 15 seconds
- one original Discord progress message is edited through stages and replaced by the final card

The first page is the summary. The same public Discord message is edited in place when its buttons
switch to Technical, GEX, Fundamentals, News, Bull vs Bear, or Risk evidence. Only the original
requester and Manager/administrator/Owner can operate those buttons; everyone may read the current
page. Provider/LLM failures are classified, audited, deduplicated in System
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
and token counts. Moomoo unavailable/permission responses are valid insufficient-data results and
must never be bypassed with invented or stale evidence. If repeated failures occur, turn off the
isolated Research kill switch; do not weaken the coverage gate.

## Post-launch validation

Revalidate live Moomoo capacity, cold/cache latency, Discord desktop/mobile shared-card UX, member
rate limits, alert recovery, cost, and all strict no-side-effect assertions. If production behavior
regresses, set `AXIS_RESEARCH_MODE=TEST` or disable the Research kill switch and restart.
