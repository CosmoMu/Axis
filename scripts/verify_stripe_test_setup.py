#!/usr/bin/env python3
from __future__ import annotations

import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import stripe  # noqa: E402

from app.config import Settings  # noqa: E402


def main() -> int:
    settings = Settings.load(PROJECT_ROOT)
    stripe_config = settings.stripe_config()
    test_config = stripe_config.test
    if not stripe_config.enabled or not test_config.runtime_ready:
        raise RuntimeError("Stripe Test configuration is incomplete")
    if not test_config.secret_key.startswith("sk_test_"):
        raise RuntimeError("Stripe key is not a Test Mode key")

    client = stripe.StripeClient(test_config.secret_key)
    product_id = test_config.day_pass_product_id or ""
    if product_id != test_config.monthly_product_id:
        raise RuntimeError("Day Pass and Monthly must share AXIS Membership product")
    product = client.v1.products.retrieve(product_id)
    day_pass = client.v1.prices.retrieve(test_config.day_pass_price_id or "")
    monthly = client.v1.prices.retrieve(test_config.monthly_price_id or "")

    if product.name != "AXIS Membership" or not product.active:
        raise RuntimeError("AXIS Membership product is missing or inactive")
    if (
        day_pass.currency != "usd"
        or day_pass.unit_amount != 999
        or day_pass.recurring is not None
        or day_pass.lookup_key != "axis_day_pass_v1"
    ):
        raise RuntimeError("Day Pass Test price does not match V1")
    if (
        monthly.currency != "usd"
        or monthly.unit_amount != 9999
        or monthly.recurring is None
        or monthly.recurring.interval != "month"
        or monthly.lookup_key != "axis_monthly_v1"
    ):
        raise RuntimeError("Monthly Test price does not match V1")

    with socket.create_connection(
        (settings.payment_webhook_host, settings.payment_webhook_port),
        timeout=3,
    ):
        pass
    print("stripe_test_setup=PASS")
    print("product=AXIS Membership")
    print("day_pass=USD 9.99 one_time DAY_PASS_V1")
    print("monthly=USD 99.99 month MONTHLY_V1 auto_renew")
    print("local_webhook=LISTENING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
