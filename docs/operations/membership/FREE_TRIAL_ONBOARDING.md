# Free Trial Onboarding Operations

## Frozen production rule

Free Trial is seven consecutive calendar days from the exact successful claim timestamp. Weekends
and U.S. market holidays count. Day Pass remains one U.S. equity trading day and is the only one of
these two products that uses `TradingCalendarService`.

## New-member flow

1. Discord shows `👋・welcome` first through category/channel ordering and public visibility.
2. The persistent Welcome card has exactly two controls: `START 7-DAY FREE TRIAL` is a Discord
   interaction and `VIEW MEMBERSHIP` links to `💳・subscriptions`.
3. Joining does not create an entitlement or assign `Member`.
4. The user selects `START 7-DAY FREE TRIAL`, reviews the current risk disclosure, and confirms
   with `I UNDERSTAND`.
5. AXIS rechecks lifetime eligibility and all active entitlements in the transaction.
6. AXIS creates a `FREE_TRIAL` entitlement with `expires_at = started_at + 7 days`, then reconciles
   the aggregate Member Role.

The join listener ignores bots/wrong Guilds and only inspects eligibility. Personalized public join
messages are prohibited. DMs remain off unless `NEW_MEMBER_FREE_TRIAL_DM_ENABLED=true`; even then a
DM only links to Welcome and never grants access.

## Eligibility outcomes

- `ELIGIBLE`: show the risk disclosure and allow explicit claim.
- `USED`: do not create another Trial; return an `AXIS FREE TRIAL` ephemeral card with
  `VIEW MEMBERSHIP`.
- `ACCESS_ACTIVE`: do not consume the Trial; the existing access remains the source of truth.
- `DISABLED`: hide/disable the offer and do not grant access.

An active Trial blocks Day Pass checkout as unnecessary, but Monthly checkout remains available.
Leaving and rejoining never resets the unique Discord User ID claim record.

## Configuration

```dotenv
NEW_MEMBER_FREE_TRIAL_ENABLED=true
NEW_MEMBER_FREE_TRIAL_CALENDAR_DAYS=7
NEW_MEMBER_FREE_TRIAL_AUTO_OFFER=true
NEW_MEMBER_FREE_TRIAL_DM_ENABLED=false
```

The deprecated `NEW_MEMBER_FREE_TRIAL_TRADING_DAYS` value is ignored. Never delete a historical
`membership_trials` row to restore eligibility. Existing claims keep their stored duration unit,
amount, start, and expiry after later configuration changes.

## Verification

Run the automated membership tests, database verifier, Discord Bootstrap dry-run, and Discord
runtime verifier. Confirm:

- database revision `20260831_0025`;
- Welcome is first among public categories/channels;
- Welcome has only `START 7-DAY FREE TRIAL` and `VIEW MEMBERSHIP`, with no long navigation manual;
- cards say `7 Calendar Days`, no card, no automatic renewal;
- Risk Disclosure says `MY RISK IS NOT YOUR RISK` and requires `I UNDERSTAND`;
- Day Pass still says `1 Trading Day`;
- no `3 Trading Days` Trial copy remains;
- a second Bootstrap makes no ordering or control-card duplicates.
