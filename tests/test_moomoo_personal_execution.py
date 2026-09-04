from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.personal_execution import PersonalBrokerEnvironment, PersonalExecutionMode
from app.integrations.moomoo_personal_execution import (
    MoomooPersonalBroker,
    PersonalBrokerError,
    mask_account_id,
)


def test_account_identifier_is_one_way_masked() -> None:
    masked = mask_account_id("123456789")
    assert masked.startswith("acct_")
    assert "123456789" not in masked
    assert masked == mask_account_id("123456789")


@pytest.mark.asyncio
async def test_dry_run_adapter_refuses_every_write_before_sdk_call() -> None:
    broker = MoomooPersonalBroker(
        host="127.0.0.1",
        port=11111,
        environment=PersonalBrokerEnvironment.SIMULATE,
        execution_mode=PersonalExecutionMode.DRY_RUN,
    )
    with pytest.raises(PersonalBrokerError, match="BROKER_WRITE_BLOCKED_DRY_RUN"):
        await broker.place_limit_order(
            contract_code="US.SPY260904C650000",
            side="BUY",
            quantity=1,
            limit_price=Decimal("1.00"),
            purpose="ENTRY",
            idempotency_key="test",
        )
    with pytest.raises(PersonalBrokerError, match="BROKER_WRITE_BLOCKED_DRY_RUN"):
        await broker.cancel_order("test-order")
