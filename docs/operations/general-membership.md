# AXIS Membership Operations

## Runtime model

Membership access is entitlement-based. `Member` Role remains present while at least one of
`FREE_TRIAL`, `DAY_PASS`, `MONTHLY`, `GIFT`, `MANUAL`, or `MANUAL_EXTENSION` is active.
Removing or expiring one entitlement must not remove the Role while another remains active.

All duration labels used by Free Trial, Day Pass, and trading-day extensions use the XNYS
calendar through `TradingCalendarService`. The last valid session expires at 23:59:59
America/New_York.

## Stripe Test Mode configuration

Keep every value in local `.env` or a Secret Manager:

```dotenv
STRIPE_ENABLED=false
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_SUCCESS_URL=
STRIPE_CANCEL_URL=
STRIPE_PORTAL_RETURN_URL=
STRIPE_DAY_PASS_PRODUCT_ID=
STRIPE_DAY_PASS_PRICE_ID=
STRIPE_DAY_PASS_PRICING_VERSION=DAY_PASS_V1
STRIPE_MONTHLY_PRODUCT_ID=
STRIPE_MONTHLY_PRICE_ID=
STRIPE_MONTHLY_PRICING_VERSION=MONTHLY_V1
```

Checkout is disabled unless `STRIPE_ENABLED=true` and every required Test Mode value is
present. The webhook endpoint is `POST /webhooks/stripe` and validates the raw body using the
`Stripe-Signature` header. Do not route the listener publicly without TLS and a restricted
reverse proxy.

The local Test deployment uses the official Stripe CLI through
`scripts/run_stripe_test_listener.py`. Its LaunchAgent is installed with
`scripts/install_axis_stripe_test_listener_service.py`, filters the five membership events, and
forwards them only to `127.0.0.1:8787`. The runner reads the Test API key from `.env`, compares the
CLI signing secret to `STRIPE_WEBHOOK_SECRET`, and redacts both API and webhook secrets from logs.
Use `scripts/verify_stripe_test_setup.py` for a read-only Product/Price/listener check. This local
listener is for Test Mode only and is not a substitute for a restricted public TLS endpoint.

`membership_prices` is the source for displayed and charged prices. The initial V1 catalog is
stored in migration `20260830_0015`; Stripe Product/Price IDs are bound from `.env`. Never edit
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

Complete both checklists before Live Mode:

- `docs/development/STRIPE_PUBLIC_PRIVACY_CHECKLIST.md`
- `docs/development/LIVE_MODE_CHECKLIST.md`
