from __future__ import annotations

import pytest

from app.bot.cogs.payment_webhook import PaymentWebhookCog
from app.services.membership_stripe import (
    MembershipStripeError,
    StripeWebhookApplication,
)


class _Response:
    status = 200

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _Client:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, *, json: dict[str, object]) -> _Response:
        self.posts.append((url, json))
        return _Response()


class _PaymentService:
    def __init__(self, error: MembershipStripeError | None = None) -> None:
        self.error = error
        self.events: list[dict[str, object]] = []

    async def process_webhook(
        self,
        guild_id: int,
        event: dict[str, object],
        *,
        actor_user_id: int,
    ) -> StripeWebhookApplication:
        assert guild_id == 1543309921066684567
        assert actor_user_id == 42
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return StripeWebhookApplication(False, 99, "ACTIVE", True)


class _User:
    id = 42


class _Bot:
    user = _User()

    def get_cog(self, name: str) -> None:
        assert name == "SystemAlertsCog"
        return None


def _cog(
    service: _PaymentService,
    synced: list[tuple[int, bool]],
) -> PaymentWebhookCog:
    async def sync_role(user_id: int, enabled: bool) -> None:
        synced.append((user_id, enabled))

    return PaymentWebhookCog(
        _Bot(),  # type: ignore[arg-type]
        guild_id=1543309921066684567,
        host="127.0.0.1",
        port=8787,
        gateway=object(),  # type: ignore[arg-type]
        payment_service=service,  # type: ignore[arg-type]
        sync_role=sync_role,
        relay_url="https://axisdesk.fyi/internal/stripe-events",
        relay_secret="local-test-secret",
    )


@pytest.mark.asyncio
async def test_relay_item_processes_syncs_and_acks() -> None:
    synced: list[tuple[int, bool]] = []
    service = _PaymentService()
    client = _Client()
    cog = _cog(service, synced)

    await cog._process_relay_item(  # noqa: SLF001
        client,  # type: ignore[arg-type]
        {
            "id": "evt_live/encoded",
            "lease_token": "lease-1",
            "attempt_count": 1,
            "event": {"id": "evt_live", "livemode": True},
        },
    )

    assert service.events == [{"id": "evt_live", "livemode": True}]
    assert synced == [(99, True)]
    assert client.posts == [
        (
            "https://axisdesk.fyi/internal/stripe-events/evt_live%2Fencoded/ack",
            {"lease_token": "lease-1"},
        )
    ]


@pytest.mark.asyncio
async def test_relay_item_schedules_retry_with_safe_error_code() -> None:
    synced: list[tuple[int, bool]] = []
    service = _PaymentService(MembershipStripeError("STRIPE_SUBSCRIPTION_NOT_LINKED"))
    client = _Client()
    cog = _cog(service, synced)

    with pytest.raises(MembershipStripeError, match="STRIPE_SUBSCRIPTION_NOT_LINKED"):
        await cog._process_relay_item(  # noqa: SLF001
            client,  # type: ignore[arg-type]
            {
                "id": "evt_retry",
                "lease_token": "lease-2",
                "attempt_count": 3,
                "event": {"id": "evt_retry", "livemode": True},
            },
        )

    assert synced == []
    assert client.posts == [
        (
            "https://axisdesk.fyi/internal/stripe-events/evt_retry/retry",
            {
                "lease_token": "lease-2",
                "error": "STRIPE_SUBSCRIPTION_NOT_LINKED",
                "attempt_count": 3,
            },
        )
    ]
