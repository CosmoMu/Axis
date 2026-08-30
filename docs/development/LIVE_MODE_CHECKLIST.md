# AXIS Membership Live Mode Checklist

Current status: **STOP FOR LIVE — local Stripe Test Checkout is enabled, but public TLS webhook,
completed payment/cancellation E2E, brand asset upload, legal business information, and the
manual privacy review are incomplete.**

## Code and database

- [x] Migration `20260830_0015` adds price catalog, acknowledgement, trial, entitlement, and
  minimal payment-event records without deleting the legacy audit tables.
- [x] Free Trial is lifetime-once per Discord user and requires versioned risk acknowledgement.
- [x] Day Pass uses one XNYS trading day; Monthly uses Stripe calendar-month billing.
- [x] Webhook event IDs are idempotent; full payment payloads are not persisted or logged.
- [x] Multiple active entitlements protect Member Role from premature removal.
- [x] Manager extension creates `MANUAL_EXTENSION` and never overwrites the source entitlement.
- [x] Public-card identity tests reject legacy/private identity content.
- [x] Production PostgreSQL backup completed immediately before applying 0015.
- [x] Production migration applied and verified at revision `20260830_0015`.

## Stripe Test Mode

- [x] Create AXIS Membership Product and current Day Pass/Monthly Prices in Stripe Test Mode.
- [x] Put Test Secret, webhook signing secret, Product IDs, Price IDs, and return URLs in `.env`.
- [ ] Expose `POST /webhooks/stripe` through a restricted HTTPS reverse proxy.
- [x] Run the local Stripe CLI Test listener with all five required membership events.
- [x] Run Test Mode Day Pass success and Monthly signup with active auto-renewal.
- [x] Verify out-of-order `invoice.paid` replay and idempotent event recovery.
- [ ] Run Monthly renewal/failure/cancel and duplicate-delivery scenarios.
- [ ] Run dynamic Customer Portal and payment-method update/cancellation tests.
- [ ] Verify grandfathering by creating a new Price without changing an existing subscription.
- [ ] Complete `STRIPE_PUBLIC_PRIVACY_CHECKLIST.md`.

## Discord and operations

- [x] Dry-run Discord blueprint: `REUSE=28 / CREATE=0 / UPDATE=0 / BLOCK=0`.
- [x] Verify Welcome, Subscriptions, Results, Lobby topic-only behavior, and Member Wins pin.
- [x] Verify Owner-only System Alerts/Card Testing and all four permission personas.
- [x] Verify all nine test-card commands in `card-testing`.
- [ ] Confirm Trial/Day Pass expiry and Member Role reconciliation in a Test Guild.
- [x] Confirm `FEATURE_LAB_ENABLED=false`, `FEATURE_MODEL_AB_ENABLED=false`, and
  `FEATURE_MOOMOO_ENABLED=false`.

## Live activation gate

- [ ] Owner manually approves every item above.
- [ ] Replace only Stripe Test keys/IDs with Live values in the Secret Manager.
- [ ] Re-register and verify the Live webhook signing secret.
- [ ] Set `STRIPE_ENABLED=true` only after approval; never commit secrets.

Do not start AXIS LAB as part of this checklist.
