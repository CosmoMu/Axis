# AXIS GEX Explorer — Current Specification

**Version:** GEX V7 Professional Ladder / Intraday Classification / 2026-09-05

**Status:** CODE COMPLETE / OWNER-ONLY TEST MODE

This is the current source of truth for AXIS GEX Explorer. It supersedes earlier V3–V6 display and
classification rules without changing Signal, Analysis, Trade, Results, Membership, Short-Term,
Swing, LEAPS, Personal Moomoo Execution, or AXIS LAB.

## Access and safety boundary

- `/gex ticker:TICKER` is Owner-only and `🧪・card-testing` only. Plain ticker messages do nothing.
- `GEX_EXPLORER_ENABLED` is the kill switch; Phase 1 accepts only `GEX_EXPLORER_MODE=TEST`.
- Member Lounge remains disabled until the Owner explicitly approves a separate launch gate.
- GEX is strictly read-only. It never writes broker orders or mutates Signal, Trade, Result,
  Analysis, Mentor, Membership, tracking state, or production history.
- GEX describes market structure. It must not output BUY CALL, BUY PUT, LONG, or SHORT.

## Data boundary

- Massive remains the production-selected source for spot, option snapshots, and real five-minute
  regular-session candles. Moomoo remains a non-blocking background candle comparison only.
- SPX/SPXW uses the provider's real SPX index/options surface and never falls back to SPY.
- Expiration selection prioritizes valid 0DTE, next expiry, nearest weeklies, and nearest monthly.
  The Discord export uses five expirations; the website selector supports 3, 5, 8, and ALL of the
  discovered 16-expiration model window.
- The first column is 0DTE whenever a valid same-day expiration exists. 0DTE is never merged into
  TOTAL. When unavailable, it is not fabricated.
- Strike rows come only from actual returned option-chain strikes. The interactive page centers
  approximately 12 listed strikes above and below spot; the Discord export uses up to 19 rows.
  The window may shift slightly when an important wall is just outside it.
- Missing Gamma/volume/OI/expiration cells display `—`; numeric zero is used only for a genuine
  calculated zero. Historical `ΔGEX` is omitted until persisted real intraday snapshots exist.

## Calculation and model boundary

- Dollar GEX per 1% move is `Gamma × weight × 100 × Spot² × 0.01`.
- The primary ladder is current-day `Volume × Gamma`; `OI × Gamma` is calculated independently and
  is never used to fill missing volume. Vendor Gamma is preferred; IV-based Black-Scholes Gamma is
  allowed only when vendor Gamma is unavailable and IV is real.
- The signed dealer convention is an explicit estimate: Call positive and Put negative. It is not
  observed dealer inventory and option volume does not reveal aggressor direction.
- Net GEX, 0DTE GEX, nearest-expiration GEX, aggregate GEX, OI × Gamma, Volume × Gamma, and distance
  from spot feed one shared classification used by both the main chart and ladder.
- Configurable Intraday Importance Score weights are: 35% 0DTE, 20% nearest expiration, 15%
  aggregate Net GEX, 10% Volume × Gamma, 10% OI × Gamma, and 10% proximity. Robust log / 90th
  percentile clipping prevents one extreme strike from suppressing the rest.
- A Gamma Node is an unusually large absolute Net GEX concentration relative to adjacent listed
  strikes and must also pass the configured score threshold.
- Major/minor resistance above spot and support below spot require positive Net GEX plus shared
  score/node/proximity evidence. Gross Call Wall and Put Wall remain separate one-sided reference
  levels and do not automatically become resistance or support.
- Negative Net GEX concentrations form Gamma acceleration zones. Pressure/support labels and
  acceleration labels are mutually exclusive at a strike.
- At most one primary Gamma Magnet may appear. It requires a positive-Gamma regime, positive Net
  GEX, adequate score, proximity, and near-term/neighbor evidence. Weak confidence returns `—`.
- Gamma Flip is calculated separately from walls and may be an interpolated level between strikes.
  The chart shows the precise value; the ladder may associate it with the nearest row as `FLIP ≈`
  without claiming that the interpolated value is an exact strike.
- Regime is Strong/Positive, Balanced/Near Flip, Negative, or Strong Negative Gamma. Explanations
  describe probabilistic pinning/mean-reversion or expansion behavior, never guaranteed direction.

## Interface hierarchy

- Keep the existing AXIS header, dark institutional style, four compact summary cards, five-minute
  candle chart, right-side labels, yellow pressure rails, teal support rails, purple acceleration
  zones, white spot line, thick dashed major levels, and dotted minor levels.
- Level 1: spot, Gamma regime, raw Call/Put Walls, nearest resistance/support, optional Magnet/Flip.
- Level 2: the main price chart shows only actionable classified levels, not every ladder strike.
- Level 3: the bottom Strike × Expiration ladder shows Strike, Role, each selected expiration,
  independently emphasized 0DTE, and TOTAL.
- Positive cells use green/teal, negative cells use purple/magenta, and unavailable/near-zero cells
  use dark neutral styling. Intensity uses robust log/percentile normalization, never a rainbow.
- The nearest listed strike row to exact spot receives a cyan/white border and SPOT marker while the
  exact spot remains visible separately.
- Roles are sparse and may include CALL WALL, PUT WALL, GAMMA MAGNET, GAMMA NODE, GAMMA FLIP,
  MAJOR/MINOR RES, MAJOR/MINOR SUP, ACCELERATION, and SPOT.
- Website cell hover/tap shows only available Net/Call/Put/OI Gamma, expiration/DTE,
  classification, and strength. Clicking a strike emphasizes it on the chart, dims unrelated minor
  levels, and exposes TOTAL plus 0DTE when available; clicking again or resetting clears it.
- Discord/mobile export is a deterministic 1800×1600 vertical image: immediate summary on top,
  price chart in the middle, and a readable ±9-strike professional ladder at the bottom.

## Reliability and verification

- Cache key is ticker + selected expirations/policy/provider; TTL, single-flight, user cooldown,
  guild rate limit, minimum expiration coverage, freshness, and latency gates remain fail-closed.
- Audit events remain GEX_REQUESTED, CACHE_HIT, CACHE_MISS, GENERATED, FAILED, and RATE_LIMITED.
  Operational failure and recovery use existing deduplicated System Alerts.
- All displayed numbers must reconcile to real provider fields or deterministic calculations. No
  LLM or image model participates in GEX levels, chart data, or the ladder.
- Test gate includes unit/regression, renderer dimension and missing-value checks, policy/config
  validation, database/runtime verification, and live read-only Massive cross-checks. Member access
  remains blocked after this gate until separately authorized.
