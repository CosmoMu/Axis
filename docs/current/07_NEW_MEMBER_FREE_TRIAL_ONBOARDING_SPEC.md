# AXIS Final Newcomer Approval / Free Trial / Security Specification

**Effective:** 2026-09-02
**Status:** CURRENT / supersedes immediate Trial claim and every earlier onboarding design

## Lifecycle lock

First join → Newcomer → restricted onboarding → Apply → Manager APPROVE / REJECT / FLAG.

Newcomer sees only `👋・welcome`, `📊・results`, and `🏆・member-wins`; all are read-only. The Role has
explicit DENY overwrites for subscriptions, lobby, Member, Manager, Owner and AXIS LAB channels so
inherited `@everyone` access cannot bypass isolation.

Welcome and the complete application/review experience are Chinese. Welcome clearly states that it
is only the welcome page, not completed access, and its only CTA is `申请加入 AXIS`. The application
collects normalized discovery source, optional referrer, multi-select interests, risk confirmation
and community safety agreement. Both agreements require the Chinese `我已阅读并同意` confirmation;
the Manager review card and its `批准` / `拒绝` / `标记` actions are also Chinese.

## Approval and membership lock

APPROVE permanently records approval, reviewer and time. If permanent Trial history is absent, the
same idempotent workflow creates a $0 Free Trial at approval time, removes Newcomer and adds Member.
After Member-role reconciliation succeeds, AXIS BOT mentions and welcomes the approved user once in
both `💬・lobby` and `🛋️・member-lounge`. Each destination stores its Discord message ID separately;
restart reconciliation retries only a missing destination and never intentionally duplicates a
completed welcome. Lobby uses a friendly community greeting; Member Lounge uses the restrained,
premium AXIS member greeting shared by paid and gifted Member activations.
There is no user claim step, card, Stripe call, or auto-renewal.

- Free Trial = exactly 3 U.S. Trading Days through `TradingCalendarService`; weekends and U.S.
  market holidays do not count.
- Day Pass = 1 U.S. Trading Day through `TradingCalendarService`.
- Monthly = Stripe calendar billing period.
- One Discord User ID = maximum one Free Trial for life.
- Database protection = unique `membership_trials(discord_user_id, trial_type)`.

Expiry marks Trial EXPIRED, retains permanent history and removes Member only when no other active
entitlement exists. It never adds Newcomer. The approved user becomes a normal `@everyone` visitor
and may later purchase Day Pass or Monthly without applying again.

Approved rejoin never receives Newcomer, another application or another Trial. Never-approved and
rejected/flagged-without-later-approval users rejoin as Newcomer.

## Security lock

`🛂・join-review` is visible only to Owner, Manager and AXIS BOT. APPROVE / REJECT / FLAG are
idempotent; rejection is not an automatic ban. Checkout services verify permanent approval even if
the user possesses an old URL/component.

Risk scanning runs on join, submission, review rendering and hourly reconciliation. Implemented
codes are VERY_NEW_ACCOUNT, NEW_ACCOUNT, PREVIOUS_REJECTION, PREVIOUS_FLAG, TRIAL_ALREADY_USED,
REJOIN_WITHOUT_APPROVAL and POSSIBLE_IMPERSONATION. Protected names come from
`config/newcomer_security.yaml`. The scanner only flags/alerts/supports review; it never bans,
kicks or rejects.

Risk rows and system alerts are deduplicated. System Status exposes aggregate NEWCOMER SECURITY
HEALTHY/ATTENTION metrics. Member and Newcomer role reconciliation repairs drift and records role
sync failures without creating another Trial.

## Production safety

Pre-gate production users must be inventoried in dry-run and baselined as approved without a Trial
before activating the gate. No Signal, Result, membership, Trial, public ID or official user history
may be reset or deleted.
