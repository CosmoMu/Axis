#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
import discord  # noqa: E402

from app.bot.cards import configure_public_identity  # noqa: E402
from app.bot.client import AxisBot  # noqa: E402
from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids, seed_guild_config  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.domain.enums import LlmWorkload  # noqa: E402
from app.domain.public_identity import PublicIdentityPolicy  # noqa: E402
from app.integrations.massive_market_data import MassiveMarketDataProvider  # noqa: E402
from app.integrations.model_router import ModelRouter, ModelRoutingError  # noqa: E402
from app.integrations.moomoo_market_data import MoomooMarketDataClient  # noqa: E402
from app.integrations.openai_analysis_parser import (  # noqa: E402
    OpenAIAnalysisParser,
    load_analysis_prompt,
    load_analysis_schema,
)
from app.integrations.openai_trade_parser import (  # noqa: E402
    OpenAITradeParser,
    TradeParseError,
    load_trade_prompt,
    load_trade_schema,
)
from app.integrations.stripe_gateway import StripeSdkGateway  # noqa: E402
from app.market_intelligence.stock_analyst import AxisStockAnalystService  # noqa: E402
from app.market_intelligence.stock_analyst.market_data import (  # noqa: E402
    MoomooDailyBarProvider,
)
from app.market_intelligence.trade_plan import SwingLeapsTradePlanService  # noqa: E402
from app.services.analysis_pipeline import AnalysisPipelineService  # noqa: E402
from app.services.attachment_storage import LocalAttachmentStore  # noqa: E402
from app.services.card_review import CardReviewService  # noqa: E402
from app.services.daily_results_review import DailyResultsReviewService  # noqa: E402
from app.services.daily_summary import DailySummaryService  # noqa: E402
from app.services.draft_generation import DraftGenerationService  # noqa: E402
from app.services.membership_access import (  # noqa: E402
    MembershipAccessService,
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
)
from app.services.membership_management import MembershipManagementService  # noqa: E402
from app.services.membership_stripe import MembershipStripeService  # noqa: E402
from app.services.mentor_management import MentorManagementService  # noqa: E402
from app.services.official_results import OfficialResultsService  # noqa: E402
from app.services.option_contracts import OptionContractResolver  # noqa: E402
from app.services.short_term_policy import ShortTermTrackingPolicy  # noqa: E402
from app.services.short_term_tracking import MarketTrackingService  # noqa: E402
from app.services.signal_input import SignalInputService  # noqa: E402
from app.services.system_alerts import SystemAlertService  # noqa: E402
from app.services.trade_publication import TradePublicationService  # noqa: E402
from app.services.trading_calendar import TradingCalendarService  # noqa: E402


async def run() -> None:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_lab_disabled()
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )
    for noisy_logger in ("discord", "httpx", "openai", "sqlalchemy"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    logging.getLogger(__name__).info(
        (
            "event=bot_start guild_id=%s analysis_enabled=%s "
            "moomoo_enabled=%s daily_summary_enabled=%s"
        ),
        settings.discord_guild_id,
        settings.analysis_enabled,
        settings.moomoo_enabled,
        settings.daily_summary_enabled,
    )
    token = settings.require_token()
    database = Database(settings.require_database_url())
    discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    try:
        async with database.session() as session:
            await seed_guild_config(
                session,
                guild_id=settings.discord_guild_id,
                discord_ids=discord_ids,
            )
            await session.commit()

        short_term_policy = ShortTermTrackingPolicy.load(settings.short_term_tracking_config_path)
        if settings.short_term_tracking_enabled and not settings.massive_api_key:
            raise ConfigurationError("Short-Term Tracking 已启用但缺少 MASSIVE_API_KEY。")
        massive_provider = (
            MassiveMarketDataProvider(
                api_key=settings.massive_api_key,
                price_source=short_term_policy.price_source,
                max_quote_age_seconds=short_term_policy.max_quote_age_seconds,
                last_trade_quote_guard_pct=(short_term_policy.last_trade_quote_guard_pct),
                base_url=settings.massive_base_url,
            )
            if settings.massive_api_key
            else None
        )
        contract_resolver = (
            OptionContractResolver(massive_provider) if massive_provider is not None else None
        )
        attachment_store = LocalAttachmentStore(
            settings.attachment_storage_path,
            max_bytes=settings.max_attachment_bytes,
        )
        draft_generation_service = None
        analysis_service = None
        if settings.openai_api_key:
            router = ModelRouter.load(
                settings.llm_routing_path,
                model_overrides={
                    LlmWorkload.SIGNAL_PARSE: settings.llm_signal_model_override,
                    LlmWorkload.SIGNAL_REPAIR: settings.llm_signal_repair_model_override,
                    LlmWorkload.ANALYSIS_PARSE: settings.llm_analysis_model_override,
                    LlmWorkload.ANALYSIS_REWRITE: (settings.llm_analysis_rewrite_model_override),
                },
                default_model_override=settings.llm_default_model_override,
                timeout_seconds_override=settings.llm_timeout_seconds,
                max_retries_override=settings.llm_max_retries,
            )
            signal_route = router.resolve(LlmWorkload.SIGNAL_PARSE)
            if signal_route.structured_output is None:
                raise ModelRoutingError("SIGNAL_PARSE 缺少 structured_output。")
            parser = OpenAITradeParser(
                api_key=settings.require_openai_api_key(),
                route=signal_route,
                schema=load_trade_schema(signal_route.structured_output),
                prompt=load_trade_prompt(settings.llm_prompt_path),
            )
            draft_generation_service = DraftGenerationService(
                database,
                attachment_store,
                parser,
                contract_resolver,
            )
            if settings.analysis_enabled:
                analysis_parse_route = router.resolve(LlmWorkload.ANALYSIS_PARSE)
                analysis_rewrite_route = router.resolve(LlmWorkload.ANALYSIS_REWRITE)
                if (
                    analysis_parse_route.structured_output is None
                    or analysis_rewrite_route.structured_output is None
                ):
                    raise ModelRoutingError("Analysis workload 缺少 structured_output。")
                analysis_schema = load_analysis_schema(analysis_parse_route.structured_output)
                analysis_prompt = load_analysis_prompt(settings.llm_analysis_prompt_path)
                analysis_service = AnalysisPipelineService(
                    database,
                    attachment_store,
                    OpenAIAnalysisParser(
                        api_key=settings.require_openai_api_key(),
                        route=analysis_parse_route,
                        schema=analysis_schema,
                        prompt=analysis_prompt,
                    ),
                    OpenAIAnalysisParser(
                        api_key=settings.require_openai_api_key(),
                        route=analysis_rewrite_route,
                        schema=load_analysis_schema(analysis_rewrite_route.structured_output),
                        prompt=analysis_prompt,
                    ),
                    analysis_schema,
                    (
                        AxisStockAnalystService(
                            host=settings.moomoo_host,
                            port=settings.moomoo_port,
                        )
                        if settings.axis_stock_analyst_enabled
                        else None
                    ),
                )
        elif settings.analysis_enabled:
            raise ConfigurationError("Analysis 已启用但缺少 OPENAI_API_KEY。")
        daily_summary_service = None
        if settings.daily_summary_enabled:
            daily_summary_service = DailySummaryService(
                database,
                (
                    MoomooMarketDataClient(settings.moomoo_host, settings.moomoo_port)
                    if settings.moomoo_enabled
                    else None
                ),
                results_review_enabled=settings.results_review_enabled,
            )
        daily_results_review_service = (
            DailyResultsReviewService(
                database,
                timezone_name=settings.results_timezone,
                final_publish_time=settings.results_final_publish_time,
            )
            if settings.results_review_enabled
            else None
        )
        short_term_tracking_service = MarketTrackingService(
            database,
            short_term_policy,
            massive_provider if settings.short_term_tracking_enabled else None,
        )
        swing_leaps_trade_plan_service = (
            SwingLeapsTradePlanService(
                MoomooDailyBarProvider(settings.moomoo_host, settings.moomoo_port)
            )
            if settings.axis_stock_analyst_enabled
            else None
        )
        calendar = TradingCalendarService()
        acknowledgements = MembershipAcknowledgementService(database)
        access_service = MembershipAccessService(database, calendar, acknowledgements)
        stripe_config = settings.stripe_config()
        active_stripe = stripe_config.active
        price_catalog = MembershipPriceCatalog(
            database, environment=stripe_config.mode.database_value
        )
        await price_catalog.bind_stripe_ids(
            "DAY_PASS",
            active_stripe.day_pass_pricing_version,
            product_id=active_stripe.day_pass_product_id,
            price_id=active_stripe.day_pass_price_id,
        )
        await price_catalog.bind_stripe_ids(
            "MONTHLY",
            active_stripe.monthly_pricing_version,
            product_id=active_stripe.monthly_product_id,
            price_id=active_stripe.monthly_price_id,
        )
        if stripe_config.enabled and not active_stripe.runtime_ready:
            raise ConfigurationError(
                "STRIPE_ENABLED=true, but "
                f"{stripe_config.mode.value} runtime configuration is incomplete."
            )
        if stripe_config.payments_enabled and not active_stripe.live_ready:
            raise ConfigurationError(
                "PAYMENTS_ENABLED=true, but the selected Stripe environment is not fully ready."
            )
        stripe_gateway = (
            StripeSdkGateway(
                secret_key=active_stripe.secret_key,
                webhook_secret=active_stripe.webhook_secret,
                success_url=active_stripe.success_url or "",
                cancel_url=active_stripe.cancel_url or "",
                portal_return_url=active_stripe.portal_return_url or "",
                mode=stripe_config.mode,
            )
            if stripe_config.runtime_ready()
            else None
        )
        membership_stripe_service = MembershipStripeService(
            database,
            stripe_gateway,
            calendar,
            acknowledgements,
            price_catalog,
            session_ttl_minutes=settings.membership_session_ttl_minutes,
            mode=stripe_config.mode,
            payments_enabled=stripe_config.payments_enabled,
        )
        membership_service = MembershipManagementService(
            database, access_service, membership_stripe_service
        )
        public_identity = PublicIdentityPolicy(
            operator_name=settings.public_operator_name,
            owner_user_id=settings.discord_owner_user_id,
            additional_forbidden_terms=settings.public_identity_forbidden_terms,
        )
        configure_public_identity(public_identity)
        bot = AxisBot(
            settings=settings,
            discord_ids=discord_ids,
            signal_input_service=SignalInputService(database, attachment_store),
            draft_generation_service=draft_generation_service,
            card_review_service=CardReviewService(database, contract_resolver),
            trade_publication_service=TradePublicationService(database, contract_resolver),
            short_term_tracking_service=short_term_tracking_service,
            mentor_service=MentorManagementService(database),
            membership_service=membership_service,
            membership_access_service=access_service,
            membership_acknowledgements=acknowledgements,
            membership_price_catalog=price_catalog,
            membership_stripe_service=membership_stripe_service,
            stripe_gateway=stripe_gateway,
            public_identity=public_identity,
            system_alert_service=SystemAlertService(database),
            results_service=OfficialResultsService(database),
            analysis_service=analysis_service,
            daily_summary_service=daily_summary_service,
            daily_results_review_service=daily_results_review_service,
            swing_leaps_trade_plan_service=swing_leaps_trade_plan_service,
        )
        async with bot:
            await bot.start(token, reconnect=True)
    finally:
        await database.dispose()


def main() -> int:
    try:
        asyncio.run(run())
    except (ConfigurationError, ModelRoutingError, TradeParseError) as exc:
        print(f"AXIS BOT 未启动：{exc}", file=sys.stderr)
        return 2
    except discord.LoginFailure:
        print("AXIS BOT 登录失败；请检查本地 .env，Token 未被输出。", file=sys.stderr)
        return 2
    except discord.PrivilegedIntentsRequired:
        print(
            "AXIS BOT 缺少 Server Members 或 Message Content Intent。",
            file=sys.stderr,
        )
        return 2
    except (aiohttp.ClientError, TimeoutError):
        print("AXIS BOT 无法连接 Discord；网络详情未写入日志。", file=sys.stderr)
        return 2
    except Exception:
        print("AXIS BOT 启动失败；敏感异常详情未写入日志。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
