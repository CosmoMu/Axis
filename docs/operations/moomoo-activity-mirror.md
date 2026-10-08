# Moomoo 1K Challenge Activity Mirror

## Runtime

The mirror is strictly read-only and uses the existing local OpenD endpoint.

```text
FEATURE_MOOMOO_ACTIVITY_MIRROR_ENABLED=true
MOOMOO_ACTIVITY_ENV=REAL
MOOMOO_ACTIVITY_SECURITY_FIRM=FUTUCA
MOOMOO_ACTIVITY_ACCOUNT_TYPE=MARGIN
MOOMOO_ACTIVITY_ACCOUNT_IDS=
MOOMOO_ACTIVITY_RECONCILE_SECONDS=30
MOOMOO_ACTIVITY_SUMMARY_TIME_ET=16:15
```

An empty `MOOMOO_ACTIVITY_ACCOUNT_IDS` requires exactly one non-master, US-authorized account that
matches the configured environment, firm, and account type. Current production scope is the unique
REAL MARGIN account identified by the Owner as 8070. `CASH`, `TFSA`, and `SIMULATE` are excluded.
If that filter becomes ambiguous, the mirror fails closed. An exact OpenD account ID may be supplied
later only through `.env`; never commit it.

## Validation

1. Confirm OpenD is running on `MOOMOO_OPEND_HOST:MOOMOO_OPEND_PORT`.
2. Run Discord Bootstrap dry-run and verify only `one_k_challenge` is missing.
3. Apply the forward Alembic migration.
4. Apply Bootstrap with the confirmed Guild ID, then restore `APPLY_CHANGES=false` and
   `DRY_RUN=true`.
5. Start AXIS BOT. The first reconcile is a quiet baseline.
6. Complete a small broker-side test fill and verify one matching private buy/sell/close entry. Order
   submission, cancellation, and rejection alone must not create a Discord message. Do not place the
   order from AXIS.

## Failure behavior

- Any Moomoo account/order/fill/position read error fails the cycle; it never triggers a write.
- A first failure creates one System Alert; repeated failures are suppressed by the existing alert
  service. Recovery produces a recovery card.
- Discord send is completed before the database notification marker is advanced. A crash may retry
  the same pending event; broker IDs prevent duplicate database records.
