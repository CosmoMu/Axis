#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.domain.personal_execution import PersonalExecutionMode  # noqa: E402
from app.integrations.moomoo_personal_execution import (  # noqa: E402
    MoomooPersonalBroker,
    PersonalBrokerError,
)


async def verify() -> int:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_personal_execution_safety()
    if settings.personal_execution_mode is not PersonalExecutionMode.DRY_RUN:
        print("result=BLOCKED reason=MODE_IS_NOT_DRY_RUN")
        return 2
    if settings.personal_auto_trading_enabled:
        print("result=BLOCKED reason=BROKER_WRITE_TOGGLE_ENABLED")
        return 2
    print("safety_gate=PASS mode=DRY_RUN broker_writes=DISABLED")

    try:
        with socket.create_connection(
            (settings.moomoo_host, settings.moomoo_port),
            timeout=2,
        ):
            pass
    except OSError:
        print("opend_connectivity=BLOCKED reason=OPEND_NOT_LISTENING")
        return 3

    broker = MoomooPersonalBroker(
        host=settings.moomoo_host,
        port=settings.moomoo_port,
        environment=settings.personal_broker_environment,
        execution_mode=settings.personal_execution_mode,
        account_id=settings.personal_moomoo_account_id,
        security_firm=settings.personal_moomoo_security_firm,
        live_write_validated=False,
    )
    try:
        account = await broker.read_account()
        positions, orders, fills = await asyncio.gather(
            broker.read_positions(),
            broker.read_orders(),
            broker.read_fills(),
        )
    except PersonalBrokerError as exc:
        print(f"broker_read=BLOCKED reason={exc.code}")
        return 3
    print(
        "broker_read=PASS "
        f"account_ref={account.account_ref} positions={len(positions)} "
        f"orders={len(orders)} fills={len(fills)}"
    )
    print("result=PASS live_switch=NOT_AUTHORIZED")
    return 0


def main() -> int:
    return asyncio.run(verify())


if __name__ == "__main__":
    raise SystemExit(main())
