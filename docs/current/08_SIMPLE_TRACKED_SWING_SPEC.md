# AXIS Swing V2 — Simple Tracked Swing

**Effective:** 2026-09-03

**Status:** Current Source of Truth

This document supersedes every older Swing rule that requires Mentor, position sizing, ADD, SL,
Runner, prediction charts, Fibonacci levels, or a trade plan for a newly created Swing order.
It does not change Short-Term, LEAPS, Analysis, Membership, Stripe, GEX, Moomoo, or AXIS LAB.

## Product split

- `SIMPLE_TRACKED_SWING` is the only mode for newly created Swing orders.
- `LEGACY_SWING` is compatibility mode for every Swing order that existed before migration
  `20260903_0029`. Legacy orders retain their original Mentor-driven event engine and UI until
  closed.
- LEAPS remains the complex Mentor-driven product.
- Short-Term remains on its existing lifecycle without any policy change.

The persisted `trades.tracking_mode` field is the authoritative boundary. New and Legacy Swing
must never be inferred from creation date or current status.

## Entry and review

Swing entry still starts in `signal-input`. The parser extracts Ticker, Expiry, Strike, Call/Put,
Entry Price, Category, and the optional LOTTO display flag. The Manager review is intentionally
minimal:

- confirmed contract;
- entry price;
- category;
- LOTTO toggle;
- edit, publish, and delete controls.

Simple Swing requires no Mentor, linked Mentor trade, position field, ADD stage, SL, Runner,
prediction chart, Fibonacci level, or trade-plan field. Its public entry uses the same compact
visual language as Short-Term but receives an independent `SW-XXXX` public ID and publishes only
to `〽️・swing`.

Changing a new draft from Short-Term to Swing creates a Simple Swing draft. Changing it to LEAPS
uses the existing Mentor-driven flow. A Legacy Swing update must remain on the Legacy flow.

## Fixed TP source and policy freeze

Simple Swing uses the exact active fixed-TP milestone list supplied by the Short-Term policy
object. No Swing-specific copy of that list is allowed. Under current `ST_TRACKING_V4`, the levels
are +10%, +20%, then +50% through +1000% in 25-percentage-point increments.

Each Swing tracking row stores `tracking_policy_version` and `price_source` at entry. A later
configuration change cannot alter an already-open order. `tp_levels_hit` and the unique event key
make every fixed TP idempotent across repeated quotes and restarts.

Sharing a milestone source does not share a lifecycle. Simple Swing has:

- no Fast Momentum Reversal;
- no Short-Term protection, breakeven, trailing stop, SL, or price-triggered stop;
- multi-day tracking through market close and overnight sessions;
- independent Swing tracking, event, and daily-snapshot tables.

## Price state

For each active Simple Swing, AXIS stores entry, current, highest, and lowest verified option
prices; their returns; quote timestamps; fixed TP history; provider/source; error state; and policy
version. High and Low Watermarks only move when a newer verified quote is accepted. Stale,
unavailable, outlier, or not-found quotes cannot trigger milestones or overwrite a valid price.

## Manual close

A close request must enter through `signal-input`, become a review draft, and require Manager
publish. Supported forms include:

```text
close SW-0001
close SW-0001 @5.20
close TSLA 10/16 400C
close TSLA 10/16 400C @5.20
```

Matching is restricted to active `SIMPLE_TRACKED_SWING` orders. An exact SW ID is preferred. A
contract match uses ticker, expiry, strike, and side. Zero matches block publication; multiple
matches require the Manager to choose from a dropdown. Input alone never closes a trade.

Publishing CLOSE records the trade event and stops Swing tracking. The optional input price is
stored as `close_reference_price`; without one, AXIS uses the latest valid tracked price when
available. A quote failure must not block a Manager-approved safe stop. The close reference is not
the official performance result.

After close, High Watermark is frozen. Public CLOSE and Daily Results use the verified lifetime
highest return from entry through the close boundary. Close Reference Price/Return remain internal
review and audit data and are not shown on the member-facing CLOSE card.

## Public tracking events

Public Simple Swing events are ENTRY, fixed TP, and Manager-approved CLOSE. There is no ADD, SL,
Runner, Momentum TP, or automatic EOD close. Internal event IDs and publication IDs never appear
on member cards.

The public TP number is derived from the frozen milestone list, not separately hard-coded. Each
level publishes at most once.

## Active View and EOD summary

The persistent `查看当前持仓订单` button returns Simple and Legacy Swing through their appropriate
renderers. For each active Simple Swing it shows:

- SW ID and contract;
- entry cost;
- highest fixed TP reached;
- lifetime highest price and return;
- latest current price, return, and timestamp;
- stale/unavailable state when a fresh quote cannot be obtained.

Opening the view performs a best-effort forced refresh. Failure falls back to the last valid quote
with a stale marker. Results paginate rather than silently truncating active orders.

At EOD, the Swing channel receives one idempotent summary of active Swing. Simple Swing rows use
the official option close when available, update the daily snapshot, and remain active. EOD is
never a CLOSE and does not reset the lifetime watermark. Closed Simple Swing is excluded from the
active section and belongs to Daily Results.

## Results

Short-Term and Swing candidate sets remain separate internally. A Simple Swing becomes eligible
only when it reaches a terminal state that day through Manager-approved CLOSE or contract expiry.
Active Simple Swing never enters Results.

The Swing result value is the frozen lifetime highest verified return. It is not the close
reference return and not merely that day's high. Review governance—include, exclude with reason,
correction audit, preview, publish claim, and immutable final snapshot—remains unchanged. The final
member-facing output is still one combined `AXIS DAILY RESULTS` post with separate Short-Term,
Swing, and LEAPS sections; no additional public Swing Results post is allowed.

## Expiry and recovery

Expiry ends tracking internally, freezes the existing High Watermark, and makes the order eligible
for that day's Swing Results. It does not publish an expiry card to the Swing channel.

On restart, AXIS:

1. registers a missing tracker for a published active Simple Swing entry;
2. completes tracker shutdown if the trade was closed after public publication but before tracker
   finalization;
3. resumes active multi-day tracking with the frozen policy version;
4. never creates a Simple tracker for `LEGACY_SWING` or LEAPS.

## Production migration lock

Migration `20260903_0029` is forward-only in production use. It adds the explicit mode and Swing
tracking tables, then classifies every pre-existing Swing row as `LEGACY_SWING`. It must not reset
IDs, delete rows, rewrite event history, clear Discord cards, or alter Mentor relationships.

At migration time AXIS had four active Legacy Swing orders. They remain on the old engine and old
UI until closed. New Simple Swing does not enter the Mentor dataset.
