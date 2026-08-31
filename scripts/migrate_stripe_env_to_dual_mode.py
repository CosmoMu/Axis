#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

LEGACY_TO_TEST = {
    "STRIPE_SECRET_KEY": "STRIPE_TEST_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET": "STRIPE_TEST_WEBHOOK_SECRET",
    "STRIPE_SUCCESS_URL": "STRIPE_TEST_SUCCESS_URL",
    "STRIPE_CANCEL_URL": "STRIPE_TEST_CANCEL_URL",
    "STRIPE_PORTAL_RETURN_URL": "STRIPE_TEST_PORTAL_RETURN_URL",
    "STRIPE_DAY_PASS_PRODUCT_ID": "STRIPE_TEST_DAY_PASS_PRODUCT_ID",
    "STRIPE_DAY_PASS_PRICE_ID": "STRIPE_TEST_DAY_PASS_PRICE_ID",
    "STRIPE_DAY_PASS_PRICING_VERSION": "STRIPE_TEST_DAY_PASS_PRICING_VERSION",
    "STRIPE_MONTHLY_PRODUCT_ID": "STRIPE_TEST_MONTHLY_PRODUCT_ID",
    "STRIPE_MONTHLY_PRICE_ID": "STRIPE_TEST_MONTHLY_PRICE_ID",
    "STRIPE_MONTHLY_PRICING_VERSION": "STRIPE_TEST_MONTHLY_PRICING_VERSION",
}


def main() -> int:
    if not ENV_PATH.exists():
        raise RuntimeError(".env does not exist")
    values = dotenv_values(ENV_PATH)
    migrated = 0
    for legacy, target in LEGACY_TO_TEST.items():
        old_value = str(values.get(legacy) or "").strip()
        target_value = str(values.get(target) or "").strip()
        if old_value and not target_value:
            set_key(str(ENV_PATH), target, old_value, quote_mode="never")
            migrated += 1
    set_key(str(ENV_PATH), "STRIPE_MODE", "test", quote_mode="never")
    # Safe migration default: a copied credential is not permission to keep the
    # external integration running. Re-enable only after the Test key is rotated
    # and the selected environment passes its readiness gate.
    set_key(str(ENV_PATH), "STRIPE_ENABLED", "false", quote_mode="never")
    set_key(str(ENV_PATH), "PAYMENTS_ENABLED", "false", quote_mode="never")
    for legacy in LEGACY_TO_TEST:
        if legacy in values:
            unset_key(str(ENV_PATH), legacy)
    os.chmod(ENV_PATH, stat.S_IRUSR | stat.S_IWUSR)
    print(f"stripe_env_migration=PASS migrated={migrated}")
    print("stripe_mode=test")
    print("stripe_enabled=false")
    print("payments_enabled=false")
    print("secret_values=REDACTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
