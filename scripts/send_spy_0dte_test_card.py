#!/usr/bin/env python3
"""Send exactly one real Moomoo SPY 0DTE capability card to AXIS card-testing."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

from app.bot.spy_0dte_cards import build_spy_capability_embed  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids  # noqa: E402
from app.services.spy_0dte_desk import (  # noqa: E402
    MoomooSpy0dteProvider,
    Spy0dtePolicy,
    latest_completed_session,
    render_capability_image,
)

ET = ZoneInfo("America/New_York")


async def run() -> int:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_spy_0dte_safety()
    if settings.spy_0dte_mode != "TEST" or settings.spy_0dte_scheduler_enabled:
        raise RuntimeError("SPY_0DTE_TEST_GATE_CLOSED")
    ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    channel_id = int(ids["channels"]["card_testing"])
    policy = Spy0dtePolicy.load(settings.spy_0dte_policy_path)
    provider = MoomooSpy0dteProvider(settings.moomoo_host, settings.moomoo_port)
    report = await provider.probe(latest_completed_session(datetime.now(ET)))
    image = render_capability_image(report, policy)
    embed = build_spy_capability_embed(report)
    form = aiohttp.FormData()
    form.add_field(
        "payload_json",
        json.dumps(
            {
                "embeds": [embed.to_dict()],
                "attachments": [{"id": 0, "filename": "axis-spy-0dte-test.png"}],
            },
            ensure_ascii=False,
        ),
        content_type="application/json",
    )
    form.add_field(
        "files[0]",
        image,
        filename="axis-spy-0dte-test.png",
        content_type="image/png",
    )
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {settings.require_token()}"}
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.post(url, data=form) as response,
    ):
        if response.status != 200:
            raise RuntimeError(f"SPY_0DTE_TEST_PUBLISH_FAILED:{response.status}")
        payload = await response.json()
    print(f"SPY 0DTE TEST card sent: message_id={payload['id']} channel_id={channel_id}")
    print(f"provider={report.provider} ready={report.ready} error={report.error_code or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
