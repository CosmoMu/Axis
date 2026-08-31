#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import stripe  # noqa: E402
from dotenv import set_key  # noqa: E402

from app.config import Settings  # noqa: E402

REQUIRED_EVENTS = (
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _save_env(values: dict[str, str]) -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(".env is required and must remain gitignored")
    for key, value in values.items():
        set_key(str(env_path), key, value, quote_mode="never")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)


def _find_product(client: stripe.StripeClient) -> dict[str, Any] | None:
    products = _plain(client.v1.products.list({"active": True, "limit": 100})).get("data", [])
    for product in products:
        metadata = product.get("metadata") or {}
        if (
            metadata.get("axis_resource") == "membership"
            or product.get("name") == "AXIS Membership"
        ):
            return product
    return None


def _ensure_price(
    client: stripe.StripeClient,
    *,
    product_id: str,
    lookup_key: str,
    unit_amount: int,
    recurring: bool,
) -> tuple[dict[str, Any], bool]:
    prices = _plain(
        client.v1.prices.list({"active": True, "lookup_keys": [lookup_key], "limit": 100})
    ).get("data", [])
    if prices:
        price = prices[0]
        interval = (price.get("recurring") or {}).get("interval")
        if (
            price.get("product") != product_id
            or price.get("currency") != "usd"
            or price.get("unit_amount") != unit_amount
            or interval != ("month" if recurring else None)
            or price.get("livemode") is not True
        ):
            raise RuntimeError(f"Existing Stripe Price {lookup_key} does not match AXIS V1")
        return price, False
    params: dict[str, Any] = {
        "product": product_id,
        "currency": "usd",
        "unit_amount": unit_amount,
        "lookup_key": lookup_key,
        "nickname": lookup_key.upper(),
        "metadata": {"axis_pricing_version": lookup_key.upper()},
    }
    if recurring:
        params["recurring"] = {"interval": "month"}
    return _plain(client.v1.prices.create(params)), True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Idempotently create AXIS Stripe Live Product, V1 Prices, and webhook"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    arguments = parser.parse_args()
    if not arguments.apply or not arguments.confirm_live:
        raise RuntimeError("Live writes require both --apply and --confirm-live")
    settings = Settings.load(PROJECT_ROOT)
    live = settings.stripe_config().live
    if not live.secret_key.startswith("sk_live_"):
        raise RuntimeError("STRIPE_LIVE_SECRET_KEY is missing or is not a Live key")
    webhook_url = urlparse(live.webhook_url or "")
    if (
        webhook_url.scheme != "https"
        or not webhook_url.netloc
        or webhook_url.path.rstrip("/") != "/webhooks/stripe"
    ):
        raise RuntimeError("STRIPE_LIVE_WEBHOOK_URL must be a stable public HTTPS endpoint")
    client = stripe.StripeClient(live.secret_key)
    # `/v1/account` is the platform-account endpoint. The typed `v1.accounts`
    # service targets Connect accounts and therefore requires an `acct_...` ID.
    account = _plain(stripe.Account.retrieve(api_key=live.secret_key))
    requirements = account.get("requirements") or {}
    if not (
        account.get("charges_enabled")
        and account.get("payouts_enabled")
        and account.get("details_submitted")
        and not requirements.get("currently_due")
        and not requirements.get("past_due")
    ):
        raise RuntimeError("Stripe Live account activation, KYC, and payouts must be complete")
    profile = account.get("business_profile") or {}
    profile_configured = profile.get("name") == "AXIS"
    product = _find_product(client)
    product_created = product is None
    product_description = (
        "Financial education, market-structure tools, research summaries, and "
        "community access. Not investment advice."
    )
    if product is None:
        product = _plain(
            client.v1.products.create(
                {
                    "name": "AXIS Membership",
                    "description": product_description,
                    "metadata": {"axis_resource": "membership", "environment": "PRODUCTION"},
                }
            )
        )
    product_id = str(product.get("id") or "")
    if not product_id:
        raise RuntimeError("Stripe Live Product ID is missing")
    if product.get("name") != "AXIS Membership" or product.get(
        "description"
    ) != product_description:
        product = _plain(
            client.v1.products.update(
                product_id,
                {
                    "name": "AXIS Membership",
                    "description": product_description,
                    "metadata": {
                        "axis_resource": "membership",
                        "environment": "PRODUCTION",
                    },
                },
            )
        )
    day_pass, day_created = _ensure_price(
        client,
        product_id=product_id,
        lookup_key="axis_day_pass_v1",
        unit_amount=999,
        recurring=False,
    )
    monthly, monthly_created = _ensure_price(
        client,
        product_id=product_id,
        lookup_key="axis_monthly_v1",
        unit_amount=9999,
        recurring=True,
    )
    endpoints = _plain(client.v1.webhook_endpoints.list({"limit": 100})).get("data", [])
    endpoint = next(
        (item for item in endpoints if item.get("url") == live.webhook_url),
        None,
    )
    endpoint_created = endpoint is None
    webhook_secret = live.webhook_secret
    if endpoint is None:
        endpoint = _plain(
            client.v1.webhook_endpoints.create(
                {
                    "url": live.webhook_url,
                    "enabled_events": list(REQUIRED_EVENTS),
                    "description": "AXIS Live Membership Webhook",
                    "metadata": {"environment": "PRODUCTION"},
                }
            )
        )
        webhook_secret = str(endpoint.get("secret") or "")
        if not webhook_secret.startswith("whsec_"):
            raise RuntimeError("New Live Webhook secret was not returned")
    elif not set(REQUIRED_EVENTS).issubset(set(endpoint.get("enabled_events") or [])):
        client.v1.webhook_endpoints.update(
            str(endpoint.get("id") or ""),
            {"enabled_events": list(REQUIRED_EVENTS)},
        )
    if not webhook_secret:
        raise RuntimeError(
            "Live endpoint already exists but STRIPE_LIVE_WEBHOOK_SECRET is not configured"
        )
    portal_params: dict[str, Any] = {
        "active": True,
        "name": "AXIS Live Membership",
        "default_return_url": live.portal_return_url,
        "business_profile": {
            "headline": "Manage your AXIS Membership",
            "privacy_policy_url": "https://axisdesk.fyi/#policies",
            "terms_of_service_url": "https://axisdesk.fyi/#policies",
        },
        "features": {
            "customer_update": {"enabled": True, "allowed_updates": ["email"]},
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {
                "enabled": True,
                "mode": "at_period_end",
                "cancellation_reason": {
                    "enabled": True,
                    "options": [
                        "too_expensive",
                        "unused",
                        "missing_features",
                        "other",
                    ],
                },
            },
            "subscription_update": {"enabled": False},
        },
        "metadata": {"axis_resource": "membership", "environment": "PRODUCTION"},
    }
    portal_configs = _plain(
        client.v1.billing_portal.configurations.list({"limit": 100})
    ).get("data", [])
    portal = next(
        (
            item
            for item in portal_configs
            if item.get("is_default") is True
            or (item.get("metadata") or {}).get("axis_resource") == "membership"
        ),
        None,
    )
    portal_created = portal is None
    if portal is None:
        client.v1.billing_portal.configurations.create(
            {key: value for key, value in portal_params.items() if key != "active"}
        )
    else:
        client.v1.billing_portal.configurations.update(
            str(portal.get("id") or ""), portal_params
        )
    _save_env(
        {
            "STRIPE_LIVE_DAY_PASS_PRODUCT_ID": product_id,
            "STRIPE_LIVE_MONTHLY_PRODUCT_ID": product_id,
            "STRIPE_LIVE_DAY_PASS_PRICE_ID": str(day_pass.get("id") or ""),
            "STRIPE_LIVE_MONTHLY_PRICE_ID": str(monthly.get("id") or ""),
            "STRIPE_LIVE_DAY_PASS_PRICING_VERSION": "DAY_PASS_V1",
            "STRIPE_LIVE_MONTHLY_PRICING_VERSION": "MONTHLY_V1",
            "STRIPE_LIVE_WEBHOOK_SECRET": webhook_secret,
        }
    )
    print("stripe_live_resource_setup=APPLIED")
    print(f"product={'CREATED' if product_created else 'REUSED'}")
    print(
        "customer_facing_business_name="
        f"{'VERIFIED' if profile_configured else 'DASHBOARD_REVIEW_REQUIRED'}"
    )
    print(f"day_pass_price={'CREATED' if day_created else 'REUSED'}")
    print(f"monthly_price={'CREATED' if monthly_created else 'REUSED'}")
    print(f"webhook={'CREATED' if endpoint_created else 'REUSED'}")
    print(f"customer_portal={'CREATED' if portal_created else 'UPDATED'}")
    print("secrets=.env_only")
    print("payments_enabled=UNCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
