# AXIS New Member Free Trial Onboarding — Current Specification

**Effective:** 2026-08-31
**Status:** CURRENT / overrides every earlier New Member Free Trial duration or onboarding rule

## Product durations

- Free Trial is **7 Calendar Days** from the exact claim timestamp. Weekends and U.S. market
  holidays count. It never calls `TradingCalendarService`.
- Day Pass is **1 U.S. Trading Day** and continues to use `TradingCalendarService` unchanged.
- Monthly remains a Stripe monthly subscription.
- The duration is frozen when the entitlement is created. Configuration changes never rewrite an
  existing Trial or its `expires_at`.

## Eligibility and activation

- Joining the Guild does not start or consume a Trial.
- A user must accept the current risk disclosure and explicitly select `START FREE TRIAL`.
- One Trial is allowed for the lifetime of each Discord User ID. Leaving/rejoining, username
  changes, or a different Guild membership state do not reset eligibility.
- Active paid, gifted, manual, or extension access prevents claiming but does not consume the Trial.
- While Trial access is active, Monthly checkout remains available and Day Pass checkout is
  blocked as unnecessary.
- Expiry removes `Member` only when no other active entitlement remains.

## New-member entry

- `👋・welcome` is the first channel in the first public AXIS category and the default public entry
  supported by Discord channel order and visibility.
- Member-only categories stay hidden from users without `Member`.
- The join listener ignores bots and other Guilds, checks eligibility only, and never grants a Role,
  starts a Trial, resets a Trial, or sends a personalized public join message.
- Direct-message onboarding is disabled by default. Discord cannot be made to force-open a channel;
  channel order, visibility, and a persistent Welcome card are the supported implementation.

## Public copy and controls

The persistent Welcome and Membership cards must distinguish:

- `Free Trial — 7 Calendar Days` — no card, no automatic renewal.
- `Day Pass — 1 Trading Day` — U.S. equity calendar; weekends and holidays do not count.
- `Monthly` — automatic monthly renewal until canceled.

Controls are `START FREE TRIAL`, Day Pass, Monthly, and `MANAGE MEMBERSHIP`. Risk acknowledgement
precedes activation. Customer-facing text remains Chinese-primary and includes the education-only,
non-investment-advice notice.

## Configuration

```dotenv
NEW_MEMBER_FREE_TRIAL_ENABLED=true
NEW_MEMBER_FREE_TRIAL_CALENDAR_DAYS=7
NEW_MEMBER_FREE_TRIAL_AUTO_OFFER=true
NEW_MEMBER_FREE_TRIAL_DM_ENABLED=false
```

`NEW_MEMBER_FREE_TRIAL_TRADING_DAYS` is deprecated and ignored by runtime business logic.

## Acceptance lock

Tests must prove exact seven-day expiry across a weekend and a U.S. market holiday, lifetime-once
enforcement, no Trial consumption for an already-entitled user, unchanged one-trading-day Day Pass,
aggregate entitlement Role retention, Welcome-first ordering, and idempotent persistent cards.
