from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from aiohttp import web
from discord.ext import commands

from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.integrations.payment_provider import PaymentProvider, PaymentProviderError
from app.services.membership_payments import MembershipPaymentError, MembershipPaymentService

logger = logging.getLogger(__name__)


class PaymentWebhookCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        host: str,
        port: int,
        secret: str,
        provider: PaymentProvider,
        payment_service: MembershipPaymentService,
        sync_role: Callable[[int, bool], Awaitable[None]],
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.host = host
        self.port = port
        self.secret = secret
        self.provider = provider
        self.payment_service = payment_service
        self.sync_role = sync_role
        self.runner: web.AppRunner | None = None

    async def cog_load(self) -> None:
        if not self.secret:
            return
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_post("/webhooks/membership", self.handle_webhook)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host=self.host, port=self.port)
        try:
            await site.start()
        except Exception:
            await self.runner.cleanup()
            self.runner = None
            raise

    async def cog_unload(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    async def handle_webhook(self, request: web.Request) -> web.Response:
        body = await request.read()
        signature = request.headers.get("X-AXIS-Signature")
        if not self.provider.verify_signature(body, signature, self.secret):
            return web.json_response({"status": "rejected"}, status=401)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise PaymentProviderError("PAYMENT_PAYLOAD_INVALID")
            event = self.provider.parse_event(payload)
            if self.bot.user is None:
                raise MembershipPaymentError("BOT_USER_UNAVAILABLE")
            result = await self.payment_service.apply_event(
                self.guild_id,
                event,
                actor_user_id=self.bot.user.id,
                payload_bytes=body,
            )
            await self.sync_role(result.discord_user_id, result.should_have_role)
            await report_system_recovery(
                self.bot,
                service="Membership Payment",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Payment → Member Role",
            )
            return web.json_response(
                {
                    "status": "duplicate" if result.duplicate else "processed",
                    "membership_status": result.membership_status,
                }
            )
        except (json.JSONDecodeError, PaymentProviderError, MembershipPaymentError) as exc:
            error_type = getattr(exc, "code", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Membership Payment",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Payment → Member Role",
                detail=str(error_type)[:200],
            )
            return web.json_response({"status": "rejected", "error": error_type}, status=400)
        except Exception as exc:
            logger.warning("event=payment_webhook_failed error_type=%s", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Membership Payment",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Payment → Member Role",
                detail=type(exc).__name__,
            )
            return web.json_response({"status": "failed"}, status=500)
