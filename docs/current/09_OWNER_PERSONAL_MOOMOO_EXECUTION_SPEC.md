# AXIS Owner-only Personal Moomoo Execution — Current Specification

**Source of truth:** `AXIS_Moomoo_Personal_Execution_Final_Spec.md` supplied by Owner

**Adopted:** 2026-09-04

**Status:** CODE COMPLETE / DRY_RUN EXTERNAL E2E PENDING / LIVE BLOCKED

This document records the current repository interpretation of the final Owner specification. It
supersedes only earlier statements that prohibited all Moomoo account, position, order, or execution
access. Model A/B, model scanning, member auto-trading, and every other AXIS LAB feature remain
deferred.

## Scope and isolation

- The layer trades only the Owner's explicitly selected Moomoo account.
- It never reads, links, or trades a member account and never exposes controls to Manager or Member.
- `💹・moomoo-trading` is visible only to Owner and AXIS BOT.
- It reuses TradeDraft, TradePublication, Trade, Discord, database, and System Alert architecture.
- Public signal delivery remains independent: personal execution failure alerts Owner but does not
  block or alter the member card.

## Safety modes

- Default is `DRY_RUN + SIMULATE + PERSONAL_AUTO_TRADING_ENABLED=false`.
- DRY_RUN executes the complete decision and persistence path but makes no broker write and creates
  no fake production fill or position.
- LIVE requires explicit feature enablement, `PERSONAL_EXECUTION_MODE=LIVE`, a REAL broker
  environment, a uniquely selected account and security firm, auto-trading enabled, and a separately
  recorded DRY_RUN acceptance gate.
- The AXIS process never calls or generates `unlock_trade`; any live unlock occurs manually in OpenD.
- All orders are LIMIT orders. Only AXIS-owned orders may be cancelled by AXIS.

## Entry eligibility and sizing

- Eligible automatic entries are approved, production Short-Term or Swing `NEW_TRADE / ENTRY`
  publications. Raw input, test cards, replay, pre-production history, LEAPS, and non-entry actions are
  excluded.
- OWNER_ONLY requires both source submitter and publisher/reviewer to be Owner. The control panel can
  switch to all eligible signals. Each eligible review also has an Owner-only AUTO/FOLLOW/SKIP
  override.
- Existing position in the same broker contract blocks automatic duplicate entry.
- Budget is 10% of account equity, clamped to $200–$500 and further capped by buying power. A contract
  that does not fit is skipped; AXIS never forces one contract over budget.
- Maximum entry is published price × 1.05. Stale quote, excessive spread, and configured volume/OI
  failures block entry.
- Entry TTL is 5 minutes for Short-Term and 30 minutes for Swing.
- Broker acknowledgement precedes the member publication attempt in LIVE mode. A rejected personal
  order does not prevent the public signal.

## Broker reconciliation and risk

- Broker position, order, and fill state is authoritative. Reconciliation imports opted-in manual
  option positions and detects manual adds, partial exits, and full exits.
- Manual adds start a new risk epoch using the new average cost; lifetime high and prior TP execution
  flags remain preserved.
- Before +30%, protection reference is -30% from average cost. At +30% it advances to breakeven. At
  +50% and above it uses a 30% drawdown from the risk high watermark.
- For one contract there is no TP50/TP100 partial. For more than one contract, TP50 receives floor(n/2),
  one runner is reserved, and the remainder is eligible at TP100. Trailing exit has priority.
- From 09:30 through 09:35 ET, entry and reconciliation continue but automated exits, milestones, and
  risk-high updates are frozen. At guard exit the risk high resets to the live broker quote.
- An approved linked Swing Close exits the unambiguous personal position in full. Ambiguous or missing
  mapping fails closed and alerts Owner.

## Persistence and operations

- Forward-only migration `20260903_0030` adds settings, position/risk epochs, orders, fills, events,
  account snapshots, and daily summaries without changing existing signal/tracking history.
- Idempotency keys protect publication entry, risk actions, broker fills, events, and daily summaries
  across retries and restarts.
- The persistent control card exposes connection/equity status, follow scope, manual sync, auto risk,
  kill switches, refresh, positions, orders, and history.
- Personal results remain separate from public AXIS Results. Account identifiers are stored and shown
  only as one-way masked references.

## Current release gate

Automated and synthetic DRY_RUN validation may pass before OpenD is available, but LIVE remains
blocked until local OpenD is running, the Owner has logged in, the target account/security firm is
explicitly selected, read-only account/position/order/fill reconciliation passes, Discord desktop and
mobile controls are accepted, and a controlled SIMULATE lifecycle is recorded. Switching LIVE is a
separate Owner decision after blockers are reported.
