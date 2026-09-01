# New Member Application

## User flow

The persistent Welcome card exposes only `APPLY TO JOIN AXIS`. The English application collects:

1. discovery source: Friend / Referral, X / Social Media, Discord, Online Community, or Other;
2. optional referrer text;
3. one or more interests: Short-Term, Swing, LEAPS, Market Analysis;
4. explicit `I AGREE` for Risk Acknowledgement;
5. explicit `I AGREE` for Community Safety Agreement.

Submission creates one `PENDING` `access_applications` row and posts an English card in
`🛂・join-review`. A database partial unique index prevents concurrent PENDING/FLAGGED duplicates.

## Manager review

- `APPROVE`: persists permanent approval, automatically creates the one-time Trial when eligible,
  removes Newcomer, and reconciles Member.
- `REJECT`: sets REJECTED and keeps Newcomer. It does not kick or ban.
- `FLAG`: sets FLAGGED and keeps Newcomer; Manager can later approve or reject the same record.

Only Owner, Manager and AXIS BOT can see join-review. All actions are idempotent and audited with
reviewer and timestamp. A rejected user may submit a later application; an open or approved user
cannot create a duplicate.

## Troubleshooting

Query `access_applications` by Discord User ID and inspect `status`, `reviewed_at`,
`reviewed_by_user_id`, `review_note`, and review message IDs. Do not edit an approval back to a
membership state: approval is permanent; entitlements control current Member access.
