# Newcomer Risk Scanner

## Scope and rules

`NewcomerRiskScanner` uses only Discord/application data available to AXIS. It never bans, kicks,
rejects, collects IP/device data, reads private DMs, or accesses brokerage/payment-private data.

Implemented rules:

- `< 7 days`: HIGH `VERY_NEW_ACCOUNT` (hierarchical; no duplicate NEW_ACCOUNT).
- `< 30 days`: MEDIUM `NEW_ACCOUNT`.
- previous REJECTED: `PREVIOUS_REJECTION`.
- previous FLAGGED: `PREVIOUS_FLAG`.
- permanent Trial history: LOW `TRIAL_ALREADY_USED` operational warning.
- rejoin without approval: LOW `REJOIN_WITHOUT_APPROVAL`.
- protected identity similarity: HIGH `POSSIBLE_IMPERSONATION`.

Protected identities are configured in `config/newcomer_security.yaml`. Matching uses Unicode/case/
space normalization and simple substitutions such as AXlS, AXIS_SUPPORT and V4LE.

## Execution and deduplication

Scanning runs on join, application submission, join-review rendering and hourly reconciliation.
`newcomer_risk_flags` has one row per Guild/User/risk code and updates timestamps/counts. High risk
also flows through existing `system_alerts` fingerprint deduplication; repeated scans update the
same condition rather than sending endless messages.

## False positives and health

For name similarity, verify the account and then rename the account or adjust the protected-name
configuration when appropriate; the next scan resolves conditions that no longer match and writes
`RISK_FLAG_RESOLVED`. Never remove a genuine Trial history warning merely to issue another Trial.

The pinned AXIS System Status card shows only aggregate `NEWCOMER SECURITY` metrics. HEALTHY means
no unresolved HIGH flags; ATTENTION means specific users must be reviewed in system-alerts or
join-review.
