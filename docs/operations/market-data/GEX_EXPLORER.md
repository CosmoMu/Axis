# AXIS GEX Explorer Operations

**Current mode:** `TEST` / Owner-only / `🧪・card-testing`

## Runtime flow

The implemented Member Lounge path accepts `gex HOOD` or `/gex ticker:HOOD`, validates Guild +
channel + role, normalizes the ticker, applies cache/rate limits,
loads Massive spot, selected option expirations, and the latest real five-minute U.S. session,
runs the shared V7 classifier, renders one Chinese Discord card plus a 1800×1600 PNG, and records
the existing GEX AuditLog events. Only the strict `gex TICKER` message shape triggers; a plain
ticker or normal lounge conversation does not. Current production remains TEST until the exact
launch approval is received; Owner `/gex` remains available in card-testing.

The code-ready Member Lounge anti-spam rules are separate from provider protection: ordinary members may make one
request every 30 seconds, and the same normalized ticker may be requested once per Guild every 60
seconds. Manager and Owner identities bypass both cooldowns. The eight-fresh-requests-per-minute
Guild provider limit, 60-second data cache, and single-flight generation still apply to everyone.

Moomoo OpenD compares five-minute bars in a background black box only. It never selects, replaces,
delays, or blocks the Massive result. GEX remains read-only and does not connect to trade execution.

## Data and calculation

- Production data: Massive spot, option snapshot, current-day option volume, OI, Gamma/IV, and
  five-minute aggregates. SPX must use real SPX data and never SPY as a proxy.
- Primary cell: `Gamma × option volume × 100 × Spot² × 0.01` per 1% underlying move.
- Independent OI metric: `Gamma × OI × 100 × Spot² × 0.01`; it does not fill missing volume.
- Call positive / Put negative is a documented dealer-sign estimate, not observed positioning.
- Vendor Gamma is preferred; Black-Scholes Gamma may use real vendor IV as fallback.
- Missing cells are `—`. Do not convert unavailable values to zero. `ΔGEX` remains absent until
  real timestamped snapshots are persisted and comparable.

## Expirations and strikes

The provider discovers up to 16 candidate expirations and requires the configured minimum valid
coverage. Valid same-day expiration is first and labeled 0DTE; otherwise the nearest valid expiry
is first. The Discord export shows five expiration columns and up to 19 actual listed strikes
centered around spot. The website offers 3 / 5 / 8 / ALL within the 16-expiration discovery window.

Never invent strike rows. A missing exact Strike × Expiration observation remains `—`.

## Shared V7 classification

`config/gex_explorer.yaml` owns all score weights and thresholds. Current score inputs are:

- 35% 0DTE Gamma concentration
- 20% nearest-expiration Gamma
- 15% aggregate Net GEX
- 10% Volume × Gamma
- 10% OI × Gamma
- 10% proximity to spot

The classifier applies log / 90th-percentile robust normalization. Gamma Nodes compare each
strike's absolute Net GEX with adjacent listed strikes. Positive-Net strikes above/below spot may
become major/minor resistance/support when their score or node strength qualifies. Negative-Net
concentrations become acceleration zones. Both the main chart and ladder consume these exact same
classifications.

At most one Gamma Magnet is allowed, and only in a positive-Gamma regime with sufficient positive
Net GEX, score, proximity, and near-term evidence. Gamma Flip is computed separately and may be
interpolated. Call Wall and Put Wall are gross one-sided references; they are never promoted to
resistance/support solely because they are walls.

## Presentation

The main AXIS chart keeps real five-minute candles, a white spot line, yellow resistance rails,
teal support rails, thick dashed major lines, dotted minor lines, purple negative-Gamma
acceleration zones, and right-side labels. It draws only actionable levels.

The professional ladder below it is continuous around spot and contains Strike, sparse Role,
expiration cells, and TOTAL. The 0DTE header is emphasized when available. Positive cells are
green/teal; negative cells are purple/magenta; near-zero/unavailable cells remain dark. Color
strength uses robust normalization.

Website hover/tap reveals only available Net/Call/Put/Volume/OI values, DTE, classification, and
strength. Clicking a strike temporarily emphasizes it on the chart and shows TOTAL plus 0DTE when
available. No GEX surface may output a directional trade instruction.

## Data status and failure behavior

Closed-market output is labeled as the latest available snapshot. Stale data is labeled
independently. Insufficient coverage, invalid data, provider/auth/rate failures, and rendering
errors fail closed and use stable error codes plus deduplicated System Alert/Recovery handling.
Secrets and full provider URLs are never logged.

## Verification

```text
.venv/bin/ruff check app tests scripts
.venv/bin/python -m compileall -q app scripts
.venv/bin/pytest -q
.venv/bin/python scripts/verify_gex_explorer.py HOOD SPY --skip-invalid --output-dir /tmp/gex-review
.venv/bin/python scripts/verify_database.py
.venv/bin/python scripts/verify_discord_runtime.py
```

Review the generated desktop/mobile image, actual strike continuity, 0DTE ordering when available,
TOTAL reconciliation, positive/negative colors, spot row, Wall-vs-level separation, single Magnet,
Gamma Flip, and non-fabrication of unavailable fields.

## Disable / rollback

Set `GEX_EXPLORER_ENABLED=false` in the deployment Secret environment and restart the Bot. No data
is deleted. Owner-only validation uses `GEX_EXPLORER_MODE=TEST`; do not switch to `MEMBER_LOUNGE`
without the exact approval `APPROVE GEX LOUNGE LAUNCH`.
