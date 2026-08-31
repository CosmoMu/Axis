from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiohttp import web
from discord.ext import commands, tasks

from app.bot.cogs.system_alerts import report_system_failure, report_system_recovery
from app.integrations.stripe_gateway import StripeGateway, StripeGatewayError
from app.services.membership_stripe import MembershipStripeError, MembershipStripeService

logger = logging.getLogger(__name__)


class PaymentWebhookCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        guild_id: int,
        host: str,
        port: int,
        gateway: StripeGateway | None,
        payment_service: MembershipStripeService,
        sync_role: Callable[[int, bool], Awaitable[None]],
        reconciliation_minutes: int = 15,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.host = host
        self.port = port
        self.gateway = gateway
        self.payment_service = payment_service
        self.sync_role = sync_role
        self.runner: web.AppRunner | None = None
        self.reconciliation_loop.change_interval(minutes=reconciliation_minutes)

    async def cog_load(self) -> None:
        if self.gateway is None:
            return
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_post("/webhooks/stripe", self.handle_webhook)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host=self.host, port=self.port)
        try:
            await site.start()
        except Exception:
            await self.runner.cleanup()
            self.runner = None
            raise
        self.reconciliation_loop.start()

    async def cog_unload(self) -> None:
        self.reconciliation_loop.cancel()
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    async def handle_webhook(self, request: web.Request) -> web.Response:
        if self.gateway is None:
            return web.json_response({"status": "disabled"}, status=503)
        body = await request.read()
        try:
            event = self.gateway.construct_event(
                body,
                request.headers.get("Stripe-Signature"),
            )
            if self.bot.user is None:
                raise MembershipStripeError("BOT_USER_UNAVAILABLE")
            result = await self.payment_service.process_webhook(
                self.guild_id,
                event,
                actor_user_id=self.bot.user.id,
            )
            if result.discord_user_id is not None and result.should_have_role is not None:
                await self.sync_role(result.discord_user_id, result.should_have_role)
            await report_system_recovery(
                self.bot,
                service="Stripe Webhook",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Stripe → Membership Access",
            )
            return web.json_response({"status": "duplicate" if result.duplicate else "processed"})
        except (StripeGatewayError, MembershipStripeError) as exc:
            error_type = exc.code
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Stripe Webhook",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Stripe → Membership Access",
                detail=error_type,
            )
            status = 401 if error_type.startswith("STRIPE_SIGNATURE") else 400
            return web.json_response({"status": "rejected", "error": error_type}, status=status)
        except Exception as exc:
            logger.warning("event=stripe_webhook_failed error_type=%s", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Stripe Webhook",
                error_type="PAYMENT_WEBHOOK_FAILED",
                affected="Stripe → Membership Access",
                detail=type(exc).__name__,
            )
            return web.json_response({"status": "failed"}, status=500)

    @tasks.loop(minutes=15)
    async def reconciliation_loop(self) -> None:
        if self.gateway is None or self.bot.user is None:
            return
        try:
            result = await self.payment_service.reconcile_subscriptions(
                self.guild_id,
                actor_user_id=self.bot.user.id,
                apply=True,
            )
            unresolved = [
                item
                for item in result.items
                if item.action
                not in {"CONSISTENT", "UPDATE_MEMBERSHIP", "CREATE_MISSING_MEMBERSHIP"}
            ]
            for item in result.items:
                if (
                    item.applied
                    and item.discord_user_id is not None
                    and item.should_have_role is not None
                ):
                    await self.sync_role(item.discord_user_id, item.should_have_role)
            if unresolved:
                await report_system_failure(
                    self.bot,
                    severity="ERROR",
                    service="Stripe Reconciliation",
                    error_type="STRIPE_RECONCILIATION_MISMATCH",
                    affected="Stripe ↔ AXIS Membership ↔ Discord Role",
                    detail=f"environment={result.environment} unresolved={len(unresolved)}",
                )
            else:
                await report_system_recovery(
                    self.bot,
                    service="Stripe Reconciliation",
                    error_type="STRIPE_RECONCILIATION_MISMATCH",
                    affected="Stripe ↔ AXIS Membership ↔ Discord Role",
                )
        except MembershipStripeError as exc:
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Stripe Reconciliation",
                error_type="STRIPE_RECONCILIATION_FAILED",
                affected="Stripe ↔ AXIS Membership ↔ Discord Role",
                detail=exc.code,
            )
        except Exception as exc:
            logger.warning("event=stripe_reconciliation_failed error_type=%s", type(exc).__name__)
            await report_system_failure(
                self.bot,
                severity="ERROR",
                service="Stripe Reconciliation",
                error_type="STRIPE_RECONCILIATION_FAILED",
                affected="Stripe ↔ AXIS Membership ↔ Discord Role",
                detail=type(exc).__name__,
            )

    @reconciliation_loop.before_loop
    async def before_reconciliation_loop(self) -> None:
        await self.bot.wait_until_ready()
