from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.bot.cogs.gex_explorer import (
    GexExplorerCog,
    gex_authorization_error,
    has_gex_cooldown_bypass,
    has_gex_lounge_access,
    parse_gex_message,
)
from app.bot.gex_cards import build_gex_embed
from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, Trade
from app.db.session import Database
from app.integrations.gex_intraday_data import (
    GexIntradayDataError,
    GexIntradayResult,
    MassiveGexIntradayProvider,
)
from app.integrations.gex_market_data import GexProviderResult
from app.integrations.massive_market_data import MarketDataProviderError
from app.market_intelligence.gex_explorer.engine import (
    build_gex_snapshot,
    calculate_gamma_exposure,
    classify_gamma_regime,
)
from app.market_intelligence.gex_explorer.heatmap import _level_label
from app.market_intelligence.gex_explorer.models import (
    GexIntradayBar,
    GexOptionContract,
    OptionSide,
)
from app.services.gex_explorer import (
    GexExplorerError,
    GexExplorerService,
    GexPolicy,
    normalize_gex_ticker,
)

GUILD_ID = 1543309921066684567
OWNER_ID = 111
CHANNEL_ID = 222
ET = ZoneInfo("America/New_York")


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
        call_volume = {90.0: 60, 95.0: 160, 100.0: 180, 105.0: 220, 110.0: 260}
        put_volume = {90.0: 300, 95.0: 80, 100.0: 100, 105.0: 80, 110.0: 60}
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
                        volume=call_volume[strike],
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
                        volume=put_volume[strike],
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


class FakeGexIntradayProvider:
    name = "fake-minute"

    def __init__(self, *, bar_count: int = 120) -> None:
        self.bar_count = bar_count
        self.calls = 0

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult:
        self.calls += 1
        now = datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
        price = 99.5
        bars = []
        for index in range(min(self.bar_count, bar_count)):
            opening = price
            close = price + math.sin(index * 0.23) * 0.12 + 0.015
            bars.append(
                GexIntradayBar(
                    timestamp_et=now + timedelta(minutes=index),
                    open=opening,
                    high=max(opening, close) + 0.08,
                    low=min(opening, close) - 0.08,
                    close=close,
                    volume=10_000 + index * 10,
                )
            )
            price = close
        return GexIntradayResult(
            ticker=ticker,
            provider=self.name,
            session_date=now.date(),
            source_timestamp=bars[-1].timestamp_et,
            bars=tuple(bars),
        )


class FailingGexIntradayProvider:
    name = "failing-minute"

    async def fetch(self, ticker: str, *, bar_count: int) -> GexIntradayResult:
        raise GexIntradayDataError("GEX_INTRADAY_UNAVAILABLE")


class FakeMoomooIntradayProvider(FakeGexIntradayProvider):
    name = "moomoo"


class FailingMoomooIntradayProvider(FailingGexIntradayProvider):
    name = "moomoo"


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


def test_massive_intraday_normalizes_only_regular_session_minutes() -> None:
    regular = datetime(2026, 9, 4, 14, 30, tzinfo=UTC)
    extended = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    payload = {
        "results": [
            {"t": int(extended.timestamp() * 1000), "o": 99, "h": 100, "l": 98, "c": 99.5},
            {
                "t": int(regular.timestamp() * 1000),
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100.5,
                "v": 1200,
            },
        ]
    }

    bars = MassiveGexIntradayProvider._normalize(payload)

    assert len(bars) == 1
    assert bars[0].timestamp_et.hour == 10
    assert bars[0].close == 100.5
    assert bars[0].volume == 1200


def test_volume_weighted_gex_uses_actual_option_volume_instead_of_oi() -> None:
    now = datetime(2026, 9, 4, 12, 0, tzinfo=ET)
    expiration = date(2026, 9, 11)
    contracts = (
        GexOptionContract("C100", expiration, 100, OptionSide.CALL, 1_000, 0.02, volume=10),
        GexOptionContract("C105", expiration, 105, OptionSide.CALL, 10, 0.02, volume=1_000),
        GexOptionContract("P95", expiration, 95, OptionSide.PUT, 10, 0.02, volume=1_000),
        GexOptionContract("P90", expiration, 90, OptionSide.PUT, 1_000, 0.02, volume=10),
    )

    oi_points, *_ = calculate_gamma_exposure(contracts, 97, now)
    volume_points, *_ = calculate_gamma_exposure(contracts, 97, now, exposure_basis="volume")
    oi_map = {point.strike: point for point in oi_points}
    volume_map = {point.strike: point for point in volume_points}
    assert oi_map[100].call_gex > oi_map[105].call_gex
    assert volume_map[105].call_gex > volume_map[100].call_gex

    snapshot = build_gex_snapshot(
        "TEST",
        97,
        contracts,
        now,
        exposure_basis="volume",
    )
    assert snapshot.exposure_basis == "volume"
    assert snapshot.call_wall == 105
    assert snapshot.put_wall == 95
    assert "成交量 GEX" in snapshot.gamma_method

    no_volume = tuple(replace(contract, volume=None) for contract in contracts)
    with pytest.raises(ValueError, match="option chain did not contain usable"):
        build_gex_snapshot("TEST", 97, no_volume, now, exposure_basis="volume")


def test_gross_call_wall_inside_negative_net_zone_is_not_a_magnet() -> None:
    now = datetime(2026, 9, 4, 12, 0, tzinfo=ET)
    expiration = date(2026, 9, 4)
    contracts = (
        GexOptionContract("C100", expiration, 100, OptionSide.CALL, 1, 0.02, volume=1_000),
        GexOptionContract("P100", expiration, 100, OptionSide.PUT, 1, 0.02, volume=2_000),
        GexOptionContract("C105", expiration, 105, OptionSide.CALL, 1, 0.02, volume=500),
        GexOptionContract("P105", expiration, 105, OptionSide.PUT, 1, 0.02, volume=10),
    )

    snapshot = build_gex_snapshot("TEST", 97, contracts, now, exposure_basis="volume")

    assert snapshot.call_wall == 100
    assert snapshot.gamma_magnet is None
    assert snapshot.by_strike[0].net_gex < 0
    assert any(zone.lower <= 100 <= zone.upper for zone in snapshot.negative_zones)
    assert 100 not in (*snapshot.major_resistance, *snapshot.minor_resistance)


def test_gex_message_parser_accepts_only_explicit_command_shape() -> None:
    assert parse_gex_message("gex spy") == "spy"
    assert parse_gex_message(" GEX $SPXW ") == "SPXW"
    assert parse_gex_message("gex：NVDA") == "NVDA"
    assert parse_gex_message("gex") is None
    assert parse_gex_message("gex spy please") is None
    assert parse_gex_message("what is gex spy") is None


def test_gex_lounge_access_accepts_member_manager_and_owner() -> None:
    kwargs = dict(
        guild_owner_id=10,
        configured_owner_id=11,
        member_role_id=20,
        manager_role_id=21,
    )
    assert has_gex_lounge_access(user_id=10, role_ids=(), **kwargs)
    assert has_gex_lounge_access(user_id=11, role_ids=(), **kwargs)
    assert has_gex_lounge_access(user_id=30, role_ids=(20,), **kwargs)
    assert has_gex_lounge_access(user_id=31, role_ids=(21,), **kwargs)
    assert not has_gex_lounge_access(user_id=32, role_ids=(22,), **kwargs)


def test_gex_authorization_supports_test_and_member_lounge_modes() -> None:
    allowed = dict(
        guild_id=GUILD_ID,
        channel_id=CHANNEL_ID,
        user_id=OWNER_ID,
        expected_guild_id=GUILD_ID,
        owner_user_id=OWNER_ID,
        card_testing_channel_id=CHANNEL_ID,
        member_lounge_channel_id=333,
        has_lounge_access=True,
        mode="TEST",
    )
    assert gex_authorization_error(**allowed) is None
    assert gex_authorization_error(**(allowed | {"user_id": 333})) == "PERMISSION_DENIED"
    assert gex_authorization_error(**(allowed | {"channel_id": 444})) == "TEST_CHANNEL_REQUIRED"
    assert gex_authorization_error(**(allowed | {"mode": "OFF"})) == "GEX_DISABLED"
    lounge = allowed | {
        "mode": "MEMBER_LOUNGE",
        "channel_id": 333,
        "user_id": 444,
    }
    assert gex_authorization_error(**lounge) is None
    assert gex_authorization_error(**(lounge | {"has_lounge_access": False})) == "PERMISSION_DENIED"
    assert gex_authorization_error(**(lounge | {"channel_id": 555})) == "MEMBER_LOUNGE_REQUIRED"
    assert gex_authorization_error(**(lounge | {"guild_id": 999})) == "PERMISSION_DENIED"
    assert (
        gex_authorization_error(
            **(
                lounge
                | {
                    "channel_id": CHANNEL_ID,
                    "user_id": OWNER_ID,
                    "has_lounge_access": False,
                }
            )
        )
        is None
    )


class _TypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_member_lounge_text_command_generates_reply() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
        policy(),
    )
    bot = MagicMock()
    bot.get_cog.return_value = None
    cog = GexExplorerCog(
        bot,
        service=service,
        guild_id=GUILD_ID,
        owner_user_id=OWNER_ID,
        card_testing_channel_id=CHANNEL_ID,
        member_lounge_channel_id=333,
        member_role_id=20,
        manager_role_id=21,
        mode="MEMBER_LOUNGE",
    )
    message = MagicMock(spec=discord.Message)
    message.id = 987
    message.content = "gex spy"
    message.author = MagicMock(spec=discord.Member)
    message.author.id = 444
    message.author.bot = False
    message.author.roles = [SimpleNamespace(id=20)]
    message.guild = SimpleNamespace(id=GUILD_ID, owner_id=999)
    message.channel = MagicMock()
    message.channel.id = 333
    message.channel.typing.return_value = _TypingContext()
    message.reply = AsyncMock()
    try:
        await cog.on_message(message)
        message.reply.assert_awaited_once()
        kwargs = message.reply.await_args.kwargs
        assert kwargs["mention_author"] is False
        assert kwargs["embed"].title.startswith("AXIS GEX · SPY")
        assert kwargs["file"].filename == "axis-gex-spy.png"
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_service_singleflight_cache_heatmap_and_audit() -> None:
    db = await database()
    provider = FakeGexProvider(delay=0.03)
    intraday = FakeGexIntradayProvider()
    service = GexExplorerService(db, provider, intraday, policy())  # type: ignore[arg-type]
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
        assert intraday.calls == 1
        assert first.snapshot.ticker == second.snapshot.ticker == "SPY"
        assert first.heatmap_png.startswith(b"\x89PNG")
        with Image.open(BytesIO(first.heatmap_png)) as image:
            assert image.size == (1800, 1600)
            rgb = image.convert("RGB")
            assert any(
                green > red and green > blue
                for red, green, blue in (
                    rgb.getpixel((x, y))
                    for x in range(400, 1650, 80)
                    for y in range(1110, 1460, 24)
                )
            )
            assert any(
                blue > green and red > green
                for red, green, blue in (
                    rgb.getpixel((x, y))
                    for x in range(400, 1650, 80)
                    for y in range(1110, 1460, 24)
                )
            )
        zero_label, _ = _level_label(first.snapshot, first.snapshot.zero_gamma or 0)
        assert "Gamma Flip" in zero_label
        assert first.used_expirations == 10
        assert first.intraday_provider == "fake-minute"
        assert first.intraday_bar_count == 78
        assert first.intraday_interval_minutes == 5
        assert first.snapshot.exposure_basis == "volume"
        assert first.snapshot.near_term_expiration is not None
        assert first.snapshot.call_wall == 110
        assert first.snapshot.put_wall == 90
        assert len(first.snapshot.major_resistance) <= policy().major_levels_per_side
        assert len(first.snapshot.minor_resistance) <= policy().minor_levels_per_side
        assert len(first.snapshot.major_support) <= policy().major_levels_per_side
        assert len(first.snapshot.minor_support) <= policy().minor_levels_per_side
        assert all(
            first.snapshot.by_strike[
                next(
                    index
                    for index, point in enumerate(first.snapshot.by_strike)
                    if point.strike == level
                )
            ].net_gex
            > 0
            for level in (
                *first.snapshot.major_resistance,
                *first.snapshot.minor_resistance,
                *first.snapshot.major_support,
                *first.snapshot.minor_support,
            )
        )
        if first.snapshot.gamma_magnet is not None:
            assert first.snapshot.gamma_magnet in {
                point.strike for point in first.snapshot.by_strike if point.net_gex > 0
            }
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
async def test_moomoo_shadow_compares_in_background_without_selecting_output() -> None:
    db = await database()
    primary = FakeGexIntradayProvider()
    primary.name = "massive"
    candidate = FakeMoomooIntradayProvider()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        primary,
        policy(),
        shadow_intraday_provider=candidate,
    )
    try:
        result = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="SPY",
            enforce_rate_limits=False,
        )
        for _ in range(10):
            if "SPY" in service.shadow_observations:
                break
            await asyncio.sleep(0)
        comparison = service.shadow_observations["SPY"]
        assert result.intraday_provider == "massive"
        assert candidate.calls == 1
        assert comparison.candidate_provider == "moomoo"
        assert comparison.overlapping_bar_count == 78
        assert comparison.close_relative_difference_pct == 0
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_moomoo_shadow_failure_does_not_block_massive_output() -> None:
    db = await database()
    primary = FakeGexIntradayProvider()
    primary.name = "massive"
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        primary,
        policy(),
        shadow_intraday_provider=FailingMoomooIntradayProvider(),
    )
    try:
        result = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="QQQ",
            enforce_rate_limits=False,
        )
        for _ in range(10):
            if "QQQ" in service.shadow_observations:
                break
            await asyncio.sleep(0)
        comparison = service.shadow_observations["QQQ"]
        assert result.intraday_provider == "massive"
        assert comparison.candidate_error_code == "GEX_INTRADAY_UNAVAILABLE"
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
    service = GexExplorerService(
        db,
        provider,
        FakeGexIntradayProvider(),
        policy(),  # type: ignore[arg-type]
    )
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
        status = next(field.value for field in embed.fields if field.name == "数据状态")
        assert "市场已收盘" in status
        assert "数据时间早于实时阈值" in status
        assert "部分到期日已跳过" in status
        assert all("Market" not in field.name for field in embed.fields)
        key_levels = next(field.value for field in embed.fields if field.name == "Gamma 关键结构")
        assert "Gamma Flip" in key_levels
        assert "Gamma Magnet" in key_levels
        intraday_levels = next(
            field.value for field in embed.fields if field.name == "日内支撑 / 压力"
        )
        assert "大压力" in intraday_levels
        assert "大支撑" in intraday_levels
        wall_reference = next(
            field.value for field in embed.fields if field.name == "Gross Wall 参考"
        )
        assert "Call Wall" in wall_reference
        assert "Put Wall" in wall_reference
        assert "不直接等同压力 / 支撑" in wall_reference
        assert "Gamma Magnet" in result.snapshot.analysis_zh[1]
        assert "不单独代表方向" in result.snapshot.analysis_zh[2]
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_user_cooldown_is_fail_closed_and_audited() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
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
async def test_ticker_cooldown_blocks_other_members_for_one_minute() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
        replace(policy(), user_cooldown_seconds=30, ticker_cooldown_seconds=60),
    )
    try:
        await service.query(guild_id=GUILD_ID, actor_user_id=201, ticker="SPY")
        with pytest.raises(GexExplorerError, match="GEX_TICKER_COOLDOWN"):
            await service.query(guild_id=GUILD_ID, actor_user_id=202, ticker="$spy")
        async with db.session() as session:
            rate_limit = await session.scalar(
                select(AuditLog)
                .where(AuditLog.action_type == "GEX_RATE_LIMITED")
                .order_by(AuditLog.created_at.desc())
            )
        assert rate_limit is not None
        assert rate_limit.after_json["error_type"] == "TICKER_COOLDOWN"
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_manager_or_owner_bypass_cooldowns_but_reuse_cache() -> None:
    db = await database()
    provider = FakeGexProvider()
    service = GexExplorerService(
        db,
        provider,  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
        policy(),
    )
    try:
        first = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="QQQ",
            bypass_cooldowns=True,
        )
        second = await service.query(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            ticker="QQQ",
            bypass_cooldowns=True,
        )
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert provider.calls == 1
    finally:
        await db.dispose()


def test_only_manager_and_owner_identities_bypass_gex_cooldowns() -> None:
    common = {
        "guild_owner_id": 10,
        "configured_owner_id": 11,
        "manager_role_id": 20,
    }
    assert has_gex_cooldown_bypass(user_id=10, role_ids=(), **common)
    assert has_gex_cooldown_bypass(user_id=11, role_ids=(), **common)
    assert has_gex_cooldown_bypass(user_id=30, role_ids=(20,), **common)
    assert not has_gex_cooldown_bypass(user_id=30, role_ids=(21,), **common)


@pytest.mark.asyncio
async def test_guild_fresh_request_limit_and_provider_failure_are_safe() -> None:
    db = await database()
    limited = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
        replace(policy(), guild_fresh_requests_per_minute=1),
    )
    try:
        await limited.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID, ticker="SPY")
        with pytest.raises(GexExplorerError, match="GEX_GUILD_RATE_LIMIT"):
            await limited.query(guild_id=GUILD_ID, actor_user_id=OWNER_ID + 1, ticker="QQQ")
    finally:
        await db.dispose()

    db = await database()
    failed = GexExplorerService(
        db,
        FailingGexProvider(),  # type: ignore[arg-type]
        FakeGexIntradayProvider(),
        policy(),
    )
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


@pytest.mark.asyncio
async def test_intraday_failure_is_fail_closed_and_audited() -> None:
    db = await database()
    service = GexExplorerService(
        db,
        FakeGexProvider(),  # type: ignore[arg-type]
        FailingGexIntradayProvider(),
        policy(),
    )
    try:
        with pytest.raises(GexExplorerError, match="GEX_INTRADAY_UNAVAILABLE"):
            await service.query(
                guild_id=GUILD_ID,
                actor_user_id=OWNER_ID,
                ticker="RDDT",
                enforce_rate_limits=False,
            )
        async with db.session() as session:
            failure = await session.scalar(
                select(AuditLog).where(AuditLog.action_type == "GEX_FAILED")
            )
        assert failure is not None
        assert failure.after_json["error_type"] == "GEX_INTRADAY_UNAVAILABLE"
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
        FakeGexIntradayProvider(),
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
