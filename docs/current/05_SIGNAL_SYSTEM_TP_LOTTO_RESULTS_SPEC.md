# AXIS Signal System — TP / LOTTO / Results Current Specification

**Effective:** 2026-08-30

This document supersedes older Short-Term Runner, Short-Term Active View, Short-Term Daily Summary,
and daily-result presentation rules. Signal Input, Review, Publish, Mentor, Analysis, and Membership
behavior not named here remains unchanged.

## Short-Term public lifecycle

- Public events are only ENTRY, fixed TP1–TP10, Momentum TP, and 停止追踪.
- Fixed levels are configured in `config/short_term_tracking.yaml`: TP1 +20%, TP2 +50%, TP3
  +100%, TP4 +150%, TP5 +200%, TP6 +300%, TP7 +400%, TP8 +500%, TP9 +750%, TP10
  +1000%.
- Each fixed level is idempotent and persisted in `tp_levels_hit`.
- Fast Momentum Reversal remains a plain `TP` and never advances the fixed TP number.
- Short-Term has no Runner card/status/milestone and never publishes SL, CLOSE, SELL, or SELL ALL.

## Tracking protection

- Before TP1: -50%.
- After TP1: entry / 0%.
- After TP2: TP1 / +20%.
- After TP3: TP2 / +50%; subsequent levels protect the immediately preceding fixed TP.
- A protection touch publishes only 停止追踪. This is AXIS tracking state, not a member SL.
- Full Entry, TP, Momentum, watermark, end, overnight, and policy-version history remains stored.

## LOTTO

- `is_lotto` is a persisted boolean on Draft and Trade and defaults to false.
- Review exposes a `LOTTO · YES/NO` toggle for SHORT_TERM, SWING, and LEAPS.
- LOTTO is display-only and must not affect category, Mentor, position, tracking, TP, protection,
  risk, or result calculation.
- Public cards, Active Position views, Daily Results, and Swing/LEAPS Daily Summaries append
  `(LOTTO)` to the contract when enabled.

## Active Position views

- Short-Term cards have no button and no Active View response.
- Swing and LEAPS retain persistent category-scoped views labeled `查看当前持仓订单`.

## Scheduled output

- Short-Term does not publish a Daily Summary.
- Swing and LEAPS each publish one Daily Summary containing 今日关闭 and 当前持仓.
- Results publishes one `AXIS DAILY RESULTS` card with SHORT-TERM, SWING, and LEAPS sections.
- A stopped Short-Term trade displays `highest_return_pct` if any fixed or Momentum TP fired;
  otherwise it displays `tracking_end_return_pct`, one trade per line.
- Closed Swing/LEAPS trades list realized TP event returns in numeric TP order and the highest
  recorded return. An SL close lists SL return and highest return.
- No totals, win rate, average profit, maximum drawdown, or multi-line Short-Term diagnostics are
  shown. The past-performance disclaimer remains.

## Explicit exclusions

This change does not authorize Stripe, pricing, AXIS LAB, Model A/B, new Analysis functions,
Swing/LEAPS Prediction Chart changes, or automated trading.
