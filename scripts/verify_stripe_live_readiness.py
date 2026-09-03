#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import stripe  # noqa: E402

from app.config import Settings  # noqa: E402

REQUIRED_EVENTS = {
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _nested(value: dict[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _status(name: str, passed: bool) -> None:
    print(f"{name}={'PASS' if passed else 'BLOCKED'}")


def _has_support(profile: dict[str, Any]) -> bool:
    return any(profile.get(key) for key in ("support_email", "support_phone", "support_url"))


def _events(values: Iterable[Any]) -> set[str]:
    return {str(item) for item in values}


def main() -> int:
    settings = Settings.load(PROJECT_ROOT)
    stripe_config = settings.stripe_config()
    live = stripe_config.live
    blockers = list(live.readiness_issues())
    privacy_review = _truthy("STRIPE_LIVE_PRIVACY_REVIEWED")
    if not privacy_review:
        blockers.append("privacy_review")
    account_activated = False
    kyc_complete = False
    bank_configured = False
    product_ready = False
    day_price_ready = False
    monthly_price_ready = False
    webhook_ready = False
    portal_ready = False
    statement_descriptor = "NOT_VERIFIED"
    business_name = "NOT_VERIFIED"
    support_ready = False
    relay_url_ready = bool(
        settings.stripe_live_webhook_relay_url
        and settings.stripe_live_webhook_relay_url.startswith("https://")
        and settings.stripe_live_webhook_relay_url.rstrip("/").endswith(
            "/internal/stripe-events"
        )
    )
    relay_secret_ready = bool(settings.stripe_live_webhook_relay_secret)
    if live.secret_key.startswith("sk_live_"):
        try:
            client = stripe.StripeClient(live.secret_key)
            # `/v1/account` verifies the platform account; `v1.accounts` is the
            # Connect-account service and requires an explicit account ID.
            account = _plain(stripe.Account.retrieve(api_key=live.secret_key))
            requirements = account.get("requirements") or {}
            account_activated = bool(account.get("charges_enabled"))
            bank_configured = bool(account.get("payouts_enabled"))
            kyc_complete = bool(account.get("details_submitted")) and not (
                requirements.get("currently_due") or requirements.get("past_due")
            )
            profile = account.get("business_profile") or {}
            business_name = str(profile.get("name") or "NOT_CONFIGURED")
            support_ready = _has_support(profile)
            statement_descriptor = str(
                _nested(account, "settings", "payments", "statement_descriptor", default="")
                or "NOT_CONFIGURED"
            )
            if live.day_pass_product_id:
                product = _plain(client.v1.products.retrieve(live.day_pass_product_id))
                product_ready = bool(
                    product.get("active")
                    and product.get("name") == "AXIS Membership"
                    and product.get("livemode") is True
                )
            if live.day_pass_price_id:
                price = _plain(client.v1.prices.retrieve(live.day_pass_price_id))
                day_price_ready = bool(
                    price.get("active")
                    and price.get("livemode") is True
                    and price.get("currency") == "usd"
                    and price.get("unit_amount") == 999
                    and price.get("recurring") is None
                    and price.get("product") == live.day_pass_product_id
                )
            if live.monthly_price_id:
                price = _plain(client.v1.prices.retrieve(live.monthly_price_id))
                recurring = price.get("recurring") or {}
                monthly_price_ready = bool(
                    price.get("active")
                    and price.get("livemode") is True
                    and price.get("currency") == "usd"
                    and price.get("unit_amount") == 14999
                    and recurring.get("interval") == "month"
                    and price.get("product") == live.monthly_product_id
                )
            endpoints = _plain(client.v1.webhook_endpoints.list({"limit": 100})).get(
                "data", []
            )
            webhook_ready = any(
                endpoint.get("status") == "enabled"
                and endpoint.get("url") == live.webhook_url
                and REQUIRED_EVENTS.issubset(_events(endpoint.get("enabled_events") or []))
                for endpoint in endpoints
                if isinstance(endpoint, dict)
            )
            configurations = _plain(
                client.v1.billing_portal.configurations.list({"limit": 100})
            ).get("data", [])
            portal_ready = any(
                configuration.get("active")
                and _nested(
                    configuration,
                    "features",
                    "payment_method_update",
                    "enabled",
                    default=False,
                )
                and _nested(
                    configuration,
                    "features",
                    "invoice_history",
                    "enabled",
                    default=False,
                )
                and _nested(
                    configuration,
                    "features",
                    "subscription_cancel",
                    "enabled",
                    default=False,
                )
                and _nested(
                    configuration,
                    "features",
                    "subscription_cancel",
                    "mode",
                )
                == "at_period_end"
                for configuration in configurations
                if isinstance(configuration, dict)
            )
        except stripe.StripeError:
            blockers.append("stripe_api_verification")
    else:
        blockers.append("live_secret_key")
    checks = {
        "stripe_account_activated": account_activated,
        "live_kyc_complete": kyc_complete,
        "bank_account_configured": bank_configured,
        "live_product_created": product_ready,
        "day_pass_live_price_created": day_price_ready,
        "monthly_live_price_created": monthly_price_ready,
        "public_https_webhook": webhook_ready,
        "live_webhook_secret": bool(live.webhook_secret),
        "customer_portal_live": portal_ready,
        "support_contact": support_ready,
        "privacy_review": privacy_review,
        "webhook_relay_url": relay_url_ready,
        "webhook_relay_secret": relay_secret_ready,
    }
    for name, passed in checks.items():
        _status(name, passed)
        if not passed:
            blockers.append(name)
    descriptor_valid = bool(
        statement_descriptor != "NOT_VERIFIED"
        and 5 <= len(statement_descriptor) <= 22
        and re.search(r"[A-Za-z]", statement_descriptor)
        and not re.search(r"[<>\\'\"*]", statement_descriptor)
    )
    _status("statement_descriptor", descriptor_valid)
    if not descriptor_valid:
        blockers.append("statement_descriptor")
    print(
        "statement_descriptor_configured="
        f"{str(statement_descriptor not in {'NOT_VERIFIED', 'NOT_CONFIGURED'}).lower()}"
    )
    print(
        "customer_facing_business_name_configured="
        f"{str(business_name not in {'NOT_VERIFIED', 'NOT_CONFIGURED'}).lower()}"
    )
    print(f"payments_enabled={str(stripe_config.payments_enabled).lower()}")
    unique_blockers = tuple(dict.fromkeys(blockers))
    print(f"live_blocker_count={len(unique_blockers)}")
    for blocker in unique_blockers:
        print(f"blocker={blocker}")
    print(f"stripe_live_readiness={'PASS' if not unique_blockers else 'BLOCKED'}")
    return 0 if not unique_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
