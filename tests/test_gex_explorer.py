from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.bot.cogs.gex_explorer import gex_authorization_error
from app.bot.gex_cards import build_gex_embed
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Trade
from app.db.session import Database
from app.integrations.gex_market_data import GexProviderResult
from app.integrations.massive_market_data import MarketDataProviderError
from app.market_intelligence.gex_explorer.engine import classify_gamma_regime
from app.market_intelligence.gex_explorer.models import GexOptionContract, OptionSide
from app.services.gex_explorer import (
    GexExplorerError,
    GexExplorerService,
    GexPolicy,
    normalize_gex_ticker,
)

GUILD_ID = 1543309921066684567
OWNER_ID = 111
CHANNEL_ID = 222


class FakeGexProvider:
    name = "fake"

    def __init__(
        self,
        *,
        expiration_count: int = 10,
        delay: float = 0,
        source_age_seconds: int = 0,
        market_status: str = "open",
    ) -> None:
        self.expiration_count = expiration_count
        self.delay = delay
        self.calls = 0
        self.source_age_seconds = source_age_seconds
        self.market_status = market_status

    async def fetch(self, ticker: str, policy: GexPolicy) -> GexProviderResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        now = datetime.now(UTC)
        expirations = tuple(date.today() + timedelta(days=index + 1) for index in range(10))
        used = expirations[: self.expiration_count]
        contracts = []
        for expiration in used:
            for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
                contracts.append(
                    GexOptionContract(
                        f"{ticker}-{expiration}-C-{strike}",
                        expiration,
                        strike,
                        OptionSide.CALL,
                        100 + int(strike),
                        gamma=0.02,
                    )
                )
                contracts.append(
                    GexOptionContract(
                        f"{ticker}-{expiration}-P-{strike}",
                        expiration,
                        strike,
                        OptionSide.PUT,
                        80 + int(110 - strike),
                        gamma=0.018,
                    )
                )
        return GexProviderResult(
            ticker=ticker,
            provider=self.name,
            spot=101.0,
            contracts=tuple(contracts),
            candidate_expirations=expirations,
            used_expirations=used,
            failed_expirations=tuple(
                (expiration, "GEX_EXPIRY_INCOMPLETE")
                for expiration in expirations[self.expiration_count :]
            ),
            source_timestamp=now - timedelta(seconds=self.source_age_seconds),
            fetched_at=now,
            market_status=self.market_status,
        )


class FailingGexProvider:
    name = "failing"

    async def fetch(self, ticker: str, policy: GexPolicy) -> GexProviderResult:
        raise MarketDataProviderError("GEX_PROVIDER_UNAVAILABLE")


def policy() -> GexPolicy:
    return GexPolicy.load(Path(__file__).parents[1] / "config" / "gex_explorer.yaml")


async def database() -> Database:
    result = Database("sqlite+aiosqlite:///:memory:")
    async with result.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with result.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()
    return result


def test_ticker_normalization_and_spx_mapping() -> None:
    assert normalize_gex_ticker("nvda") == "NVDA"
    assert normalize_gex_ticker("$NVDA") == "NVDA"
    assert normalize_gex_ticker("SPXW") == "SPX"
    with pytest.raises(GexExplorerError, match="GEX_TICKER_INVALID"):
        normalize_gex_ticker("NVDA please")


def test_five_level_gamma_regime_is_policy_deterministic() -> None:
    assert classify_gamma_regime(0.30) == "强正 Gamma"
    assert classify_gamma_regime(0.10) == "正 Gamma"
    assert classify_gamma_regime(0.00) == "Gamma 平衡区"
    assert classify_gamma_regime(-0.10) == "负 Gamma"
    assert classify_gamma_regime(-0.30) == "强负 Gamma"


def test_phase_one_authorization_is_owner_and_card_testing_only() -> None:
    allowed = dict(
        guild_id=GUILD_ID,
        channel_id=CHANNEL_ID,
        user_id=OWNER_ID,
        expected_guild_id=GUILD_ID,
        owner_user_id=OWNER_ID,
        card_testing_channel_id=CHANNEL_ID,
        mode="TEST",
    )
    assert gex_authorization_error(**allowed) is None
    assert gex_authorization_error(**(allowed | {"user_id": 333})) == "PERMISSION_DENIED"
    assert (
        gex_authorization_error(**(allowed | {"channel_id": 444}))
        == "TEST_CHANNEL_REQUIRED"
    )
    assert gex_authorization_error(**(allowed | {"mode": "OFF"})) == "GEX_DISABLED"


@pytest.mark.asyncio
async def test_service_singleflight_cache_heatmap_and_audit() -> None:
    db = await database()
    provider = FakeGexProvider(delay=0.03)
    service = GexExplorerService(db, provider, policy())  # type: ignore[arg-type]
    try:
        first, second = await asyncio.gather(
            service.query(
                guild_id=GUILD_ID,
                actor_user_id=OWNER_ID,
                ticker="spy",
                enforce_rate_limits=False,
            ),
            service.query(
                guild_id=GUILD_ID,
                actor_user_id=OWNER_ID,
                ticker="$SPY",
                enforce_rate_limits=False,
            ),
        )
        cached = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="SPY",
            enforce_rate_limits=False,
        )
        assert provider.calls == 1
        assert first.snapshot.ticker == second.snapshot.ticker == "SPY"
        assert first.heatmap_png.startswith(b"\x89PNG")
        assert first.used_expirations == 10
        assert first.snapshot.near_term_expiration is not None
        assert cached.cache_hit is True
        async with db.session() as session:
            actions = list(
                await session.scalars(
                    select(AuditLog.action_type).where(AuditLog.entity_type == "gex_request")
                )
            )
        assert actions.count("GEX_REQUESTED") == 3
        assert "GEX_CACHE_MISS" in actions
        assert "GEX_GENERATED" in actions
        assert "GEX_CACHE_HIT" in actions
        async with db.session() as session:
            assert await session.scalar(select(func.count()).select_from(Trade)) == 0
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_partial_expiry_success_and_closed_stale_labels() -> None:
    db = await database()
    provider = FakeGexProvider(
        expiration_count=6,
        source_age_seconds=600,
        market_status="closed",
    )
    service = GexExplorerService(db, provider, policy())  # type: ignore[arg-type]
    try:
        result = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="NVDA",
            enforce_rate_limits=False,
        )
        assert result.used_expirations == 6
        assert result.stale is True
        embed = build_gex_embed(result)
        status = next(field.value for field in embed.fields if field.name == "Data Status")
        assert "MARKET CLOSED" in status
        assert "STALE DATA" in status
        assert "部分到期日已跳过" in status
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_user_cooldown_is_fail_closed_and_audited() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        replace(policy(), user_cooldown_seconds=60),
    )
    try:
        await service.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID, ticker="AAPL")
        with pytest.raises(GexExplorerError, match="GEX_USER_COOLDOWN"):
            await service.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID, ticker="AAPL")
        async with db.session() as session:
            actions = list(await session.scalars(select(AuditLog.action_type)))
        assert "GEX_RATE_LIMITED" in actions
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_guild_fresh_request_limit_and_provider_failure_are_safe() -> None:
    db = await database()
    limited = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        replace(policy(), guild_fresh_requests_per_minute=1),
    )
    try:
        await limited.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID, ticker="SPY")
        with pytest.raises(GexExplorerError, match="GEX_GUILD_RATE_LIMIT"):
            await limited.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID + 1, ticker="QQQ")
    finally:
        await db.dispose()

    db = await database()
    failed = GexExplorerService(db, FailingGexProvider(), policy())  # type: ignore[arg-type]
    try:
        with pytest.raises(GexExplorerError, match="GEX_PROVIDER_UNAVAILABLE"):
            await failed.query(
                guild_id=GUILD_ID,
                actor_user_id=OWNER_ID,
                ticker="TSLA",
                enforce_rate_limits=False,
            )
        async with db.session() as session:
            failure = await session.scalar(
                select(AuditLog).where(AuditLog.action_type == "GEX_FAILED")
            )
        assert failure is not None
        assert failure.after_json["error_type"] == "GEX_PROVIDER_UNAVAILABLE"
    finally:
        await db.dispose()


def test_runtime_config_mirror_matches_policy() -> None:
    root = Path(__file__).parents[1]
    assert (root / "config" / "gex_explorer.yaml").read_bytes() == (
        root / "docs" / "config-reference" / "gex_explorer.yaml"
    ).read_bytes()


@pytest.mark.asyncio
async def test_service_rejects_insufficient_expiration_coverage() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(expiration_count=4),  # type: ignore[arg-type]
        policy(),
    )
    try:
        with pytest.raises(GexExplorerError, match="GEX_EXPIRY_COVERAGE_INSUFFICIENT"):
            await service.query(
                guild_id=GUILD_ID,
                actor_user_id=OWNER_ID,
                ticker="QQQ",
                enforce_rate_limits=False,
            )
    finally:
        await db.dispose()
