# AXIS Moomoo Production Market Data — Current Specification

**Effective:** 2026-09-13

Moomoo OpenD is the Production market-data source for Stock Analyst, GEX option surface, GEX
intraday bars, Short-Term/Swing option tracking and post-close option quotes.

The four provider selections must be explicit and accept only `moomoo` or `massive`. There is no
silent fallback. When all are `moomoo`, AXIS must start with an empty `MASSIVE_API_KEY` and must not
instantiate Massive market providers. Massive adapter code remains available only for a deliberate,
configured rollback with valid entitlement.

All analysis, GEX classification, TP, Swing, Results and Discord presentation logic remains
unchanged. Provider timestamps remain authoritative; stale data may not be made fresh using request
time. Missing OI, volume, IV or Gamma may not be substituted or invented.

SPX must never map to SPY. Until OpenD exposes a reliable SPX underlying snapshot, GEX SPX returns
`SPX_PROVIDER_UNSUPPORTED`; this isolated limitation does not block SPY/QQQ/equity support.

Personal Moomoo execution remains a separate Owner-only release gate. This specification never
enables LIVE broker writes.
