from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import stripe

from app.integrations.stripe_config import StripeMode


class StripeGatewayError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class StripeCheckout:
    id: str
    url: str


@dataclass(frozen=True, slots=True)
class StripeSubscriptionSnapshot:
    id: str
    customer_id: str | None
    status: str
    cancel_at_period_end: bool
    current_period_end: datetime | None
    created_at: datetime | None
    metadata: dict[str, str]
    price_id: str | None


class StripeGateway(Protocol):
    mode: StripeMode

    async def create_checkout(
        self,
        *,
        price_id: str,
        membership_session_id: str,
        discord_user_id: int,
        membership_type: str,
        pricing_version: str,
        monthly: bool,
    ) -> StripeCheckout: ...

    async def create_portal(self, *, customer_id: str) -> str: ...

    async def cancel_at_period_end(self, *, subscription_id: str) -> None: ...

    async def cancel_subscription(self, *, subscription_id: str) -> None: ...

    async def list_subscriptions(self) -> tuple[StripeSubscriptionSnapshot, ...]: ...

    def construct_event(self, body: bytes, signature: str | None) -> dict[str, Any]: ...


class StripeSdkGateway:
    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str,
        success_url: str,
        cancel_url: str,
        portal_return_url: str,
        mode: StripeMode = StripeMode.TEST,
    ) -> None:
        if not all((secret_key, webhook_secret, success_url, cancel_url, portal_return_url)):
            raise StripeGatewayError("STRIPE_CONFIGURATION_INCOMPLETE")
        expected_prefix = "sk_live_" if mode is StripeMode.LIVE else "sk_test_"
        if not secret_key.startswith(expected_prefix):
            raise StripeGatewayError("STRIPE_KEY_MODE_MISMATCH")
        if not webhook_secret.startswith("whsec_"):
            raise StripeGatewayError("STRIPE_WEBHOOK_SECRET_INVALID")
        self.mode = mode
        self.client = stripe.StripeClient(secret_key)
        self.webhook_secret = webhook_secret
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.portal_return_url = portal_return_url

    async def create_checkout(
        self,
        *,
        price_id: str,
        membership_session_id: str,
        discord_user_id: int,
        membership_type: str,
        pricing_version: str,
        monthly: bool,
    ) -> StripeCheckout:
        metadata = {
            "discord_user_id": str(discord_user_id),
            "membership_type": membership_type,
            "pricing_version": pricing_version,
            "membership_session_id": membership_session_id,
            "environment": self.mode.metadata_value,
        }
        params: dict[str, Any] = {
            "mode": "subscription" if monthly else "payment",
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": membership_session_id,
            "metadata": metadata,
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
        }
        if monthly:
            params["subscription_data"] = {"metadata": metadata}
        try:
            result = await asyncio.to_thread(self.client.v1.checkout.sessions.create, params)
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_CHECKOUT_CREATE_FAILED") from exc
        url = str(result.url or "")
        if not result.id or not url:
            raise StripeGatewayError("STRIPE_CHECKOUT_URL_MISSING")
        return StripeCheckout(str(result.id), url)

    async def create_portal(self, *, customer_id: str) -> str:
        try:
            result = await asyncio.to_thread(
                self.client.v1.billing_portal.sessions.create,
                {"customer": customer_id, "return_url": self.portal_return_url},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_PORTAL_CREATE_FAILED") from exc
        url = str(result.url or "")
        if not url:
            raise StripeGatewayError("STRIPE_PORTAL_URL_MISSING")
        return url

    async def cancel_at_period_end(self, *, subscription_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.v1.subscriptions.update,
                subscription_id,
                {"cancel_at_period_end": True},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_SUBSCRIPTION_UPDATE_FAILED") from exc

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.v1.subscriptions.cancel,
                subscription_id,
                {},
            )
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_SUBSCRIPTION_CANCEL_FAILED") from exc

    async def list_subscriptions(self) -> tuple[StripeSubscriptionSnapshot, ...]:
        params: dict[str, Any] = {"status": "all", "limit": 100}
        snapshots: list[StripeSubscriptionSnapshot] = []
        try:
            while True:
                page = await asyncio.to_thread(self.client.v1.subscriptions.list, params)
                data = list(page.data or [])
                snapshots.extend(_subscription_snapshot(item) for item in data)
                if not page.has_more or not data:
                    break
                params["starting_after"] = str(data[-1].id)
        except stripe.StripeError as exc:
            raise StripeGatewayError("STRIPE_SUBSCRIPTION_LIST_FAILED") from exc
        return tuple(snapshots)

    def construct_event(self, body: bytes, signature: str | None) -> dict[str, Any]:
        if not signature:
            raise StripeGatewayError("STRIPE_SIGNATURE_MISSING")
        try:
            event = stripe.Webhook.construct_event(body, signature, self.webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise StripeGatewayError("STRIPE_SIGNATURE_INVALID") from exc
        return _plain_dict(event)


def _plain_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_dict(item) for item in value]
    return value


def _subscription_snapshot(value: Any) -> StripeSubscriptionSnapshot:
    plain = _plain_dict(value)
    items = plain.get("items") if isinstance(plain, dict) else None
    item_data = items.get("data") if isinstance(items, dict) else None
    price_id = None
    period_values: list[datetime] = []
    if isinstance(item_data, list):
        for item in item_data:
            if not isinstance(item, dict):
                continue
            price = item.get("price")
            if price_id is None and isinstance(price, dict):
                price_id = str(price.get("id") or "") or None
            period_end = item.get("current_period_end")
            if isinstance(period_end, (int, float)):
                period_values.append(datetime.fromtimestamp(period_end, tz=UTC))
    direct_period_end = plain.get("current_period_end")
    if isinstance(direct_period_end, (int, float)):
        period_values.append(datetime.fromtimestamp(direct_period_end, tz=UTC))
    created = plain.get("created")
    raw_metadata = plain.get("metadata")
    metadata = (
        {str(key): str(item) for key, item in raw_metadata.items()}
        if isinstance(raw_metadata, dict)
        else {}
    )
    customer = plain.get("customer")
    customer_id = (
        customer
        if isinstance(customer, str)
        else str(customer.get("id") or "") if isinstance(customer, dict) else None
    )
    return StripeSubscriptionSnapshot(
        id=str(plain.get("id") or ""),
        customer_id=customer_id or None,
        status=str(plain.get("status") or "").lower(),
        cancel_at_period_end=bool(plain.get("cancel_at_period_end", False)),
        current_period_end=max(period_values) if period_values else None,
        created_at=(
            datetime.fromtimestamp(created, tz=UTC)
            if isinstance(created, (int, float))
            else None
        ),
        metadata=metadata,
        price_id=price_id,
    )
