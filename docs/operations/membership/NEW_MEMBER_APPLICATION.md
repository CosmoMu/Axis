# New Member Application

## User flow

The persistent Chinese Welcome card explicitly states that it is only the welcome page and does not
itself grant access. It exposes only `申请加入 AXIS` and tells users that clicking this button and
submitting the application is required to enter the review flow. All user-facing application,
agreement, submission-status and Manager review copy is Chinese. The application itself collects:

1. discovery source: 朋友推荐、X / 社交媒体、Discord、网络社区或其他；
2. optional referrer text;
3. one or more interests: Short-Term, Swing, LEAPS, Market Analysis;
4. explicit `我已阅读并同意` for risk confirmation;
5. explicit `我已阅读并同意` for the community safety agreement.

Submission creates one `PENDING` `access_applications` row and posts a Chinese card in
`🛂・join-review`. A database partial unique index prevents concurrent PENDING/FLAGGED duplicates.

## Manager review

- `批准` (`APPROVE` internally): persists permanent approval, automatically creates the one-time Trial when eligible,
  removes Newcomer, reconciles Member, then mentions and welcomes the approved user in both
  `💬・lobby` and `🛋️・member-lounge`.
- `拒绝` (`REJECT` internally): sets REJECTED and keeps Newcomer. It does not kick or ban.
- `标记` (`FLAG` internally): sets FLAGGED and keeps Newcomer; Manager can later approve or reject
  the same record.

Only Owner, Manager and AXIS BOT can see join-review. All actions are idempotent and audited with
reviewer and timestamp. A rejected user may submit a later application; an open or approved user
cannot create a duplicate.

## Troubleshooting

Query `access_applications` by Discord User ID and inspect `status`, `reviewed_at`,
`reviewed_by_user_id`, `review_note`, and review message IDs. Do not edit an approval back to a
membership state: approval is permanent; entitlements control current Member access.

Lobby and Member Lounge welcome messages are tracked independently on the approved application.
The Member Lounge welcome includes clickable Short-Term, Swing, and LEAPS channel mentions sourced
from the registered Discord channel configuration; channel IDs are not hard-coded in the message.
The five-minute reconciliation loop retries a destination only while its message ID is absent and
the user still has active Member access, so restart recovery does not duplicate completed welcomes.
Bot-managed Approval Role changes are marked as expected before Discord mutation; they must never
be imported by the manual-role listener as a lifetime MANUAL entitlement.
