# Simple Tracked Swing Operations

Product authority: `docs/current/08_SIMPLE_TRACKED_SWING_SPEC.md`.

This runbook covers only new `SIMPLE_TRACKED_SWING`. Existing `LEGACY_SWING` and LEAPS continue
through the original Mentor-driven workflow.

## Entry lifecycle

1. A Manager sends a new option idea to `signal-input`.
2. The parser resolves the contract and tags a new Swing as `SIMPLE_TRACKED_SWING`.
3. `signal-review` shows contract, entry price, category, LOTTO, Edit, Publish, and Delete.
4. Publish creates the SW trade/event/publication, sends the compact entry card, and registers the
   independent Swing tracker.
5. The tracker stores the exact verified option ticker and starts from the published entry price.

Simple Swing must not ask for Mentor or Position and must not render ADD, SL, Runner, structure
chart, Fib, or trade-plan controls. If those controls appear, do not publish; inspect
`trades.tracking_mode` and the draft payload.

## Shared TP milestones and freezing

`SwingTrackingService` receives the same active `ShortTermTrackingPolicy` instance as Short-Term
and reads `policy.tp_levels`. There is no Swing milestone config or duplicated hard-coded ladder.
The current V4 ladder is +10%, +20%, and +50% through +1000% in 25-point increments.

At registration, the tracker persists `tracking_policy_version` and `price_source`. Open trades
continue using that version if future configuration changes. Each reached level is appended to
`tp_levels_hit`; the event uniqueness constraint and publication claim prevent duplicate cards.

Simple Swing intentionally does not run Short-Term momentum or protection rules.

## Inspect active Swing

The supported member/Manager view is the persistent `查看当前持仓订单` button under a Swing card.
It performs a best-effort quote refresh and shows SW ID, contract, entry cost, highest TP, High,
Current, return, quote time, and any stale marker. The view paginates when required.

For read-only database diagnosis:

```sql
SELECT t.public_trade_id, t.tracking_mode, t.state,
       st.tracking_state, st.entry_price, st.current_price,
       st.highest_price, st.highest_return_pct, st.highest_tp_level,
       st.last_quote_at, st.last_data_error, st.tracking_policy_version
FROM trades AS t
LEFT JOIN swing_tracking AS st ON st.trade_id = t.id
WHERE t.category = 'SWING'
ORDER BY t.public_trade_id;
```

Never change production price state directly for routine troubleshooting.

## High Watermark

Only a newer verified provider quote can advance High or Low Watermark. TP cards are generated from
the accepted quote and frozen policy. A stale, missing, outlier, or unresolved contract quote sets
an order-level error and cannot overwrite valid state or trigger a TP.

High freezes when the tracker becomes `CLOSED` or `EXPIRED`. Official Close and Results performance
is always `(highest_price / entry_price - 1) * 100`, not the latest quote or today's high.

## Send and review CLOSE

Use `signal-input`:

```text
close SW-0001
close SW-0001 @5.20
close TSLA 10/16 400C
close TSLA 10/16 400C @5.20
```

An SW ID matches one active Simple Swing. A contract form matches active Simple Swing using ticker,
expiry, strike, and Call/Put. No match blocks publication. Multiple matches add a dropdown and the
Manager must choose the intended order. The input message never stops tracking by itself.

The review card shows the target order, contract, current lifetime High, and optional Close
Reference. Publish writes the CLOSE event/publication and then stops the tracker. If a live quote
cannot be fetched, the Manager-approved close still succeeds using the optional reference or last
valid price as context.

`close_reference_price` and `close_reference_return_pct` are internal review/audit fields only and
are not shown on the member-facing CLOSE card. Public CLOSE and Daily Result use the frozen
lifetime High.

## Active View quote fallback

The button first attempts a forced provider refresh. If the provider returns no eligible quote,
the response uses the last valid tracked value and labels it stale/unavailable. It must not invent
a price, downgrade the High Watermark, or block access to the remainder of the active list.

## EOD Swing Summary

The existing EOD job produces one idempotent Swing message. Active Simple Swing uses the official
same-day option close when available, updates `swing_daily_snapshots`, and remains active across
the close. EOD is not a sell instruction and never resets lifetime High/Low state.

Closed/expired Simple Swing is omitted from Active Summary. Legacy Swing continues to render
through its previous summary path.

## Swing Results Review

A Simple Swing is eligible only when Manager CLOSE or expiry made it terminal on that trading day.
Active orders do not enter Results. The candidate's return is the frozen lifetime verified High.

Short-Term and Swing candidates are built separately inside `daily_results_reviews/items`.
Manager include/exclude/correction governance remains unchanged. Public output is still one
combined `AXIS DAILY RESULTS` message; never manually publish an extra Swing result post.

## Restart recovery

On startup the Swing cog:

- registers a missing tracker for a published active Simple Swing entry;
- reconciles a trade already marked CLOSED whose tracker finalization was interrupted;
- resumes each active tracker with its stored policy version;
- skips Legacy Swing and LEAPS.

After restart, compare tracking rows and unpublished event claims before treating a repeat card as
a Discord-only issue.

## Contract expiry

Expiry internally changes the tracker to `EXPIRED`, closes the trade, freezes the existing High,
and makes the order eligible for that day's Results. No expiry card is sent to `〽️・swing`.
Expiry is independent of Short-Term lifecycle code despite the shared milestone source.

## Legacy Swing

Migration `20260903_0029` marked every pre-existing Swing `LEGACY_SWING`; four were Active at
migration. Legacy orders retain Mentor, Position, ADD/TP/SL/Runner/Close, chart, Active View, and
summary behavior until closed. Never relabel them as Simple and never create a `swing_tracking` row
for them.

## Bad quote correction

First inspect the verified option code, quote timestamp, source, last error, and provider response.
If the code is wrong, correct it through the reviewed business workflow or a dedicated audited
migration—never by silently editing High/Low values. If an authentic historical quote was missed,
prepare a narrowly scoped, reviewed backfill that records source, timestamp, before/after values,
and affected TP events. Do not lower a previously verified High without explicit incident approval.

## Diagnose tracking failure

1. Confirm the bot process is running and database revision is `20260903_0029`.
2. Run `.venv/bin/python scripts/verify_database.py` without printing connection details.
3. Verify the trade is `SIMPLE_TRACKED_SWING`, active, and has exactly one tracker.
4. Verify option ticker, expiry, frozen policy version, source, and `last_data_error`.
5. Compare `last_quote_at` with the current market session and provider health.
6. Inspect unpublished `swing_tracking_events` before retrying publication.
7. Check `system-alerts` for provider ERROR/RECOVERY; order-level stale/not-found states are
   recoverable data-quality issues and should not create alert storms.
8. Restart only after preserving logs and read-only evidence. Registration and event publication
   are idempotent, but confirm no separate bot instance is running.

Secrets must remain in `.env` or the deployment Secret Store. Never paste API keys, database URLs,
signed webhook values, or customer/Discord identifiers into commands, tickets, logs, or Git.
