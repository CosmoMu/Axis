#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp  # noqa: E402
import stripe  # noqa: E402

from app.config import Settings  # noqa: E402
from app.integrations.stripe_config import StripeMode  # noqa: E402


def _signature(secret: str, body: bytes, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


async def replay(event_id: str) -> int:
    settings = Settings.load(PROJECT_ROOT)
    stripe_config = settings.stripe_config()
    test_config = stripe_config.test
    if stripe_config.mode is not StripeMode.TEST:
        raise RuntimeError("Local replay requires STRIPE_MODE=test")
    if not test_config.secret_key.startswith("sk_test_"):
        raise RuntimeError("Only a Stripe Test key may replay local events")
    if not test_config.webhook_secret.startswith("whsec_"):
        raise RuntimeError("Stripe Test webhook secret is missing")
    if settings.payment_webhook_host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Replay destination must be local")

    event = stripe.StripeClient(test_config.secret_key).v1.events.retrieve(event_id)
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = int(time.time())
    url = f"http://{settings.payment_webhook_host}:{settings.payment_webhook_port}/webhooks/stripe"
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": _signature(test_config.webhook_secret, body, timestamp),
    }
    async with (
        aiohttp.ClientSession() as session,
        session.post(url, data=body, headers=headers) as response,
    ):
        result = await response.json(content_type=None)
        status = str(result.get("status") or "unknown") if isinstance(result, dict) else "unknown"
        print(f"stripe_test_replay={response.status} status={status} event={event_id[:8]}...")
        return 0 if response.status == 200 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay one Stripe Test event to local AXIS")
    parser.add_argument("event_id")
    arguments = parser.parse_args()
    if not arguments.event_id.startswith("evt_"):
        parser.error("event_id must start with evt_")
    return asyncio.run(replay(arguments.event_id))


if __name__ == "__main__":
    raise SystemExit(main())
