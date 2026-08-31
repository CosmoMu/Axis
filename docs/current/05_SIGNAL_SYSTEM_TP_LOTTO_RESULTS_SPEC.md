# AXIS Signal System — TP / LOTTO / Results Current Specification

**Effective:** 2026-08-31

This document supersedes older Short-Term Runner, Short-Term Active View, Short-Term Daily Summary,
and daily-result presentation rules. Signal Input, Review, Publish, Mentor, Analysis, and Membership
behavior not named here remains unchanged.

## Short-Term public lifecycle

- Public events are only ENTRY, fixed TP1–TP41, Momentum TP, and 停止追踪.
- New tracking uses `ST_TRACKING_V4` from `config/short_term_tracking.yaml`: TP1 +10%, TP2 +20%,
  then one fixed TP every 25 percentage points from TP3 +50% through TP41 +1000%.
- Existing orders keep their frozen policy version. `ST_TRACKING_V2` and `ST_TRACKING_V3` remain
  available from their versioned config files for orders already tracking under former ladders.
- Each fixed level is idempotent and persisted in `tp_levels_hit`.
- Fast Momentum Reversal remains a plain `TP` and never advances the fixed TP number.
- Short-Term has no Runner card/status/milestone and never publishes SL, CLOSE, SELL, or SELL ALL.

## Tracking protection

- Before TP1: -50%.
- After TP1 (+10%): entry / 0%.
- After TP2 (+20%): entry / 0%.
- From TP3 (+50%) onward: protect the immediately preceding fixed TP; TP3 protects +20%, TP4
  protects +50%, and so on.
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
- Every Short-Term trade displays that trading day's `highest_return_pct`, whether it stopped that
  day or remains under tracking. Current return and tracking-end return stay internal.
- Short-Term result lines contain only the option code and return, for example
  `MU 970C +52.94%`; public `ST-XXXX` IDs and LOTTO labels are omitted from this section.
- Closed Swing/LEAPS trades list realized TP event returns in numeric TP order and the highest
  recorded return. An SL close lists SL return and highest return.
- No totals, win rate, average profit, maximum drawdown, or multi-line Short-Term diagnostics are
  shown. The past-performance disclaimer remains.

## Daily Results Review / Exclude workflow

- 每个实际 XNYS 交易日收盘后 `RESULTS_REVIEW_DRAFT_DELAY_MINUTES` 分钟生成唯一 Draft；Early
  Close 使用当日真实 close time。
- Eligible Items 包含当天 STOPPED Short-Term、收盘时仍为 ACTIVE / OVERNIGHT_ACTIVE 的全部
  Short-Term，以及当天 CLOSED Swing / LEAPS，默认全部 Included；Loss Trade 不自动隐藏。
- `📋・results-review` 仅 Manager、Owner 与 AXIS BOT 可见。操作为 MANAGE TRADES、EDIT CARD、
  PREVIEW 与 PUBLISH NOW。
- Exclude / Re-Include 只改变当天公开快照，保存 actor、time、reason 与 before/after Audit，
  永不删除 Trade、Event、Tracking、Mentor Dataset 或内部历史。
- 普通 Edit 只修改 Public Display。收益纠错必须走 Correct Result，保存 original、corrected、
  reason、actor 与 time。
- `RESULTS_FINAL_PUBLISH_TIME` 默认 `16:15 ET`；无人审核时仍发布所有默认 Included Items。
  Publish Now 和 Scheduled Publish 共用幂等 claim，Bot 重启不得重复 Draft 或 Public Message。
- Published 后普通 Include / Exclude 锁定；`final_snapshot` 不可变。后续 Public Correction
  只能通过独立 Audit Workflow，并保持会员当日原始可见快照可追溯。
- Review / Final 不显示 Daily Totals；Swing / LEAPS Category Summary 不受 Exclude 影响。

## Soft Open production boundary

- `2026-08-31` 起真实输入默认为 PRODUCTION，并永久保存。
- 之后禁止第二次全量 Reset、重新编号或清除 Production History。
- Fake Signal、Fake Result、Synthetic Event 和 Preview 只允许在 `🧪・card-testing` 的 TEST
  Environment 中运行，不得污染 Production 数据。

## Explicit exclusions

This change does not authorize Stripe, pricing, AXIS LAB, Model A/B, new Analysis functions,
Swing/LEAPS Prediction Chart changes, or automated trading.
