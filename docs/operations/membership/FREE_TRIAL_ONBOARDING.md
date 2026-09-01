# Approved Newcomer Free Trial Operations

## Frozen duration rules

- Free Trial: seven consecutive Calendar Days from the approval timestamp. Weekends and U.S.
  market holidays count. `TradingCalendarService` is not called.
- Day Pass: one U.S. Trading Day through `TradingCalendarService`.
- Monthly: Stripe calendar billing period.

## Final flow

1. First join after cutover adds `Newcomer` and isolates the user to welcome/results/member-wins.
2. Welcome exposes only `APPLY TO JOIN AXIS`.
3. The user completes the English Application, Risk Acknowledgement and Community Safety Agreement.
4. Manager approves in `🛂・join-review`.
5. AXIS rechecks permanent Trial history inside the approval workflow.
6. AXIS creates `FREE_TRIAL` with `expires_at = approval timestamp + 7 Calendar Days`, removes
   Newcomer and adds Member. There is no separate claim or confirmation button.

At expiry, AXIS marks the Trial EXPIRED and reconciles all other entitlements. Without another
active entitlement, Member is removed. Newcomer is never added because approval is permanent; the
user becomes a normal `@everyone` visitor.

## Permanent lifetime protection

Query `membership_trials` using `discord_user_id` and `trial_type='FREE_TRIAL'`. The database
constraint `membership_trial_lifetime_once` is unique across those fields. Rows are never deleted
at expiry. `application_id` and `approved_by_user_id` preserve the approval origin.

Double click, concurrent approve, retry and restart all converge on the same Trial row. A duplicate
attempt returns `FREE_TRIAL_ALREADY_CLAIMED` and writes `FREE_TRIAL_DUPLICATE_BLOCKED` audit evidence.
The Trial uses $0, no card, no Stripe Checkout and no renewal.

## Verification

Confirm:

- database revision `20260831_0026`;
- Welcome contains only `APPLY TO JOIN AXIS`;
- Risk and Community agreements each require `I AGREE`;
- Approval automatically creates exactly one seven-day entitlement;
- Membership Trial has no trading-day fields for new claims;
- Trial expiry removes Member only when aggregate access is inactive;
- approved rejoin never creates Newcomer or another Trial;
- Day Pass still says and behaves as `1 Trading Day`.
