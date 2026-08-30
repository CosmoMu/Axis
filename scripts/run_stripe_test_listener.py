#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402

STRIPE_TEST_EVENTS = (
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)
_SECRET_PATTERN = re.compile(r"(?:sk_(?:test|live)|whsec)_[A-Za-z0-9]+")


def redact_stripe_output(value: str) -> str:
    return _SECRET_PATTERN.sub("<redacted>", value.rstrip())


def run() -> int:
    settings = Settings.load(PROJECT_ROOT)
    if not settings.stripe_enabled:
        logging.error("event=stripe_test_listener_disabled")
        return 2
    if not settings.stripe_secret_key.startswith("sk_test_"):
        logging.error("event=stripe_test_listener_invalid_api_key")
        return 2
    if not settings.stripe_webhook_secret.startswith("whsec_"):
        logging.error("event=stripe_test_listener_invalid_webhook_secret")
        return 2

    stripe_cli = os.getenv("STRIPE_CLI_PATH", "").strip() or shutil.which("stripe")
    if stripe_cli is None:
        fallback = Path("/usr/local/bin/stripe")
        stripe_cli = str(fallback) if fallback.is_file() else None
    if stripe_cli is None:
        logging.error("event=stripe_test_listener_cli_missing")
        return 2

    environment = os.environ.copy()
    environment["STRIPE_API_KEY"] = settings.stripe_secret_key
    forward_url = (
        f"http://{settings.payment_webhook_host}:{settings.payment_webhook_port}/webhooks/stripe"
    )
    command = [
        stripe_cli,
        "listen",
        "--skip-update",
        "--events",
        ",".join(STRIPE_TEST_EVENTS),
        "--forward-to",
        forward_url,
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    expected_secret = settings.stripe_webhook_secret
    for line in process.stdout:
        discovered = _SECRET_PATTERN.search(line)
        if (
            discovered is not None
            and discovered.group(0).startswith("whsec_")
            and discovered.group(0) != expected_secret
        ):
            logging.error("event=stripe_test_listener_secret_mismatch")
            process.terminate()
            return 2
        cleaned = redact_stripe_output(line)
        if cleaned:
            logging.info("event=stripe_cli message=%s", cleaned)
    return process.wait()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )
    try:
        return run()
    except (OSError, ValueError):
        logging.exception("event=stripe_test_listener_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
