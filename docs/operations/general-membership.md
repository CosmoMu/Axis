# AXIS Membership Operations

## Runtime model

Membership access is entitlement-based. `Member` Role remains present while at least one of
`FREE_TRIAL`, `DAY_PASS`, `MONTHLY`, `GIFT`, `MANUAL`, or `MANUAL_EXTENSION` is active.
Removing or expiring one entitlement must not remove the Role while another remains active.

Free Trial is three XNYS trading days from approval; weekends and U.S. market holidays do not
count. Free Trial, Day Pass and explicit trading-day extensions use `TradingCalendarService`; their
last valid session expires at 23:59:59 America/New_York.

`👋・welcome` is the first public AXIS entry. Joining starts the application flow; Manager approval
creates the Trial automatically after the required risk acknowledgement. Full onboarding operations
are documented in `membership/FREE_TRIAL_ONBOARDING.md`.

## Stripe environment configuration

Keep every value in local `.env` or a Secret Manager:

```dotenv
STRIPE_MODE=test
PAYMENTS_ENABLED=false

STRIPE_TEST_SECRET_KEY=
STRIPE_TEST_PUBLISHABLE_KEY=
STRIPE_TEST_WEBHOOK_SECRET=
STRIPE_TEST_WEBHOOK_URL=

STRIPE_LIVE_SECRET_KEY=
STRIPE_LIVE_PUBLISHABLE_KEY=
STRIPE_LIVE_WEBHOOK_SECRET=
STRIPE_LIVE_WEBHOOK_URL=
```

Checkout is disabled unless `PAYMENTS_ENABLED=true` and every required value for the selected
`STRIPE_MODE` is present. Test and Live never share keys, IDs, endpoint secrets or database event
namespaces. The webhook endpoint is `POST /webhooks/stripe` and validates the raw body using the
`Stripe-Signature` header. Do not route the listener publicly without TLS and a restricted
reverse proxy.

The local Test deployment uses the official Stripe CLI through
`scripts/run_stripe_test_listener.py`. Its LaunchAgent is installed with
`scripts/install_axis_stripe_test_listener_service.py`, filters the five membership events, and
forwards them only to `127.0.0.1:8787`. The runner reads the Test API key from `.env`, compares the
CLI signing secret to `STRIPE_WEBHOOK_SECRET`, and redacts both API and webhook secrets from logs.
Use `scripts/verify_stripe_test_setup.py` for a read-only Product/Price/listener check. This local
listener is for Test Mode only and is not a substitute for a restricted public TLS endpoint.
Stripe can deliver the first `invoice.paid` before `checkout.session.completed`; the first
attempt is rejected until the signed Checkout links the subscription. Stripe retries non-2xx
deliveries in hosted environments. For the local CLI Test listener, replay that Test event with
`scripts/replay_stripe_test_event.py evt_...` after Checkout is processed. The replay tool refuses
Live keys and non-local destinations and never prints the event payload or signing secret.
After Test Checkout and any required replay, run `scripts/verify_stripe_test_e2e.py` to verify
both paid Entitlements, the processed Monthly invoice, and the Discord Member Role without
printing customer, subscription, Checkout, or Discord user identifiers.

`membership_prices` is the source for displayed and charged prices. The initial V1 catalog is
split by environment in migration `20260831_0023`; Stripe Product/Price IDs are bound from `.env`. Never edit
an existing purchased price version or migrate an active subscription automatically. Create a
new current version instead.

## Source of truth and retries

Stripe webhook events—not Discord button clicks or success redirects—activate paid access.
`payment_events` stores only the minimal processing record and provider event ID. It never
stores full payment payloads. Duplicate Stripe events are idempotent.

`invoice.payment_failed` moves Monthly to `PAST_DUE` and retains access for Stripe retries.
Access is removed only after a final invalid subscription event, and only if no other active
entitlement remains.

## Public identity

Public-facing identity is `AXIS`, `AXIS BOT`, and the optional anonymous operator persona
configured by `PUBLIC_OPERATOR_NAME=VALE`. Stripe products use `AXIS Membership` and neutral
market-analysis language. Private owner identity and contact details must never be inserted in
Checkout copy, receipts, invoices, Portal content, metadata visible to customers, or Discord
cards.

Complete `docs/development/LIVE_MODE_CHECKLIST.md` before Live Mode. Full payment setup, pricing,
webhook, reconciliation, rotation and incident procedures are in `docs/operations/payments/`.
