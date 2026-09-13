"""AXIS SPY 0DTE market-structure desk (Moomoo-only, fail closed)."""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from app.market_intelligence.gex_explorer.engine import build_gex_snapshot
from app.market_intelligence.gex_explorer.heatmap import render_gex_heatmap
from app.market_intelligence.gex_explorer.models import (
    GexIntradayBar,
    GexOptionContract,
    GexSnapshot,
    OptionSide,
)

ET = ZoneInfo("America/New_York")
SPY_CODE = "US.SPY"


class Spy0dteError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Spy0dtePolicy:
    version: str
    enabled: bool
    mode: str
    start_time_et: str
    end_time_et: str
    refresh_minutes: int
    smoothing_current: float
    weights: dict[str, float]
    intraday_interval_minutes: int = 5
    heatmap_expiration_columns: int = 1
    heatmap_strike_rows: int = 19

    @classmethod
    def load(cls, path: Path) -> Spy0dtePolicy:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise Spy0dteError("SPY_0DTE_POLICY_INVALID")
        score = payload.get("score")
        smoothing = payload.get("smoothing")
        if not isinstance(score, dict) or not isinstance(smoothing, dict):
            raise Spy0dteError("SPY_0DTE_POLICY_INVALID")
        policy = cls(
            version=str(payload.get("version") or ""),
            enabled=bool(payload.get("enabled", False)),
            mode=str(payload.get("mode") or "TEST").upper(),
            start_time_et=str(payload.get("start_time_et") or "09:35"),
            end_time_et=str(payload.get("end_time_et") or "16:00"),
            refresh_minutes=int(payload.get("refresh_minutes") or 5),
            smoothing_current=float(smoothing.get("current") or 0.70),
            weights={str(key): float(value) for key, value in score.items()},
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        required = {
            "gex",
            "price_structure",
            "vwap",
            "ema9",
            "volume",
            "momentum",
            "key_level_position",
        }
        if (
            not self.version
            or self.mode not in {"TEST", "MEMBER"}
            or self.refresh_minutes != 5
            or set(self.weights) != required
            or abs(sum(self.weights.values()) - 1.0) > 1e-9
            or not 0 < self.smoothing_current <= 1
        ):
            raise Spy0dteError("SPY_0DTE_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class SpyCapabilityReport:
    checked_at: datetime
    chain_session: date
    opend_connected: bool
    spy_chain: bool
    spy_only: bool
    contract_count: int
    gamma: bool
    implied_volatility: bool
    open_interest: bool
    volume: bool
    bid_ask: bool
    timestamps: bool
    spy_spot: bool
    spy_5m: bool
    spot: float | None
    bar_count: int
    error_code: str | None
    provider: str = "moomoo"

    @property
    def ready(self) -> bool:
        return all(
            (
                self.opend_connected,
                self.spy_chain,
                self.spy_only,
                self.gamma,
                self.implied_volatility,
                self.open_interest,
                self.volume,
                self.bid_ask,
                self.timestamps,
                self.spy_spot,
                self.spy_5m,
            )
        )


@dataclass(frozen=True, slots=True)
class SpyScoreInputs:
    gex: float
    price_structure: float
    vwap: float
    ema9: float
    volume: float
    momentum: float
    key_level_position: float


@dataclass(frozen=True, slots=True)
class SpyScore:
    raw_score: int
    display_score: int
    structure_label: str


@dataclass(frozen=True, slots=True)
class Spy0dteSnapshot:
    session_date: date
    generated_at: datetime
    spot: float
    spot_timestamp: datetime
    raw_score: int
    display_score: int
    structure_label: str
    gamma_regime: str
    net_gex: float
    gamma_flip: float | None
    gamma_magnet: float | None
    call_wall: float | None
    put_wall: float | None
    supports: tuple[float, ...]
    resistances: tuple[float, ...]
    vwap: float
    ema9_5m: float
    volume_ratio: float | None
    momentum: str
    volume_gamma_bias: str
    oi_gamma_bias: str
    expected_move: float | None
    option_contract_count: int
    source_timestamp: datetime
    provider: str
    stale: bool
    warnings: tuple[str, ...]
    policy_version: str
    gex: GexSnapshot
    bars: tuple[GexIntradayBar, ...]


def structure_label(score: int) -> str:
    if score >= 70:
        return "极强偏多"
    if score >= 50:
        return "明显偏多"
    if score >= 20:
        return "轻微偏多"
    if score <= -70:
        return "极强偏空"
    if score <= -50:
        return "明显偏空"
    if score <= -20:
        return "轻微偏空"
    return "中性"


def calculate_score(
    inputs: SpyScoreInputs,
    policy: Spy0dtePolicy,
    *,
    previous_display_score: int | None = None,
) -> SpyScore:
    values = {
        name: max(-100.0, min(100.0, float(getattr(inputs, name)))) for name in policy.weights
    }
    raw = round(sum(values[name] * policy.weights[name] for name in policy.weights))
    display = raw
    if previous_display_score is not None:
        display = round(
            raw * policy.smoothing_current + previous_display_score * (1 - policy.smoothing_current)
        )
    display = max(-100, min(100, display))
    return SpyScore(raw, display, structure_label(display))


class MoomooSpy0dteProvider:
    """Read-only capability boundary for the real SPY ETF and SPY options."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def probe(self, chain_session: date) -> SpyCapabilityReport:
        return await asyncio.to_thread(self._probe_sync, chain_session)

    async def snapshot(
        self,
        session_date: date,
        policy: Spy0dtePolicy,
        *,
        previous_display_score: int | None = None,
    ) -> Spy0dteSnapshot:
        return await asyncio.to_thread(
            self._snapshot_sync,
            session_date,
            policy,
            previous_display_score,
        )

    def _snapshot_sync(
        self,
        session_date: date,
        policy: Spy0dtePolicy,
        previous_display_score: int | None,
    ) -> Spy0dteSnapshot:
        try:
            from moomoo import RET_OK, AuType, KLType, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise Spy0dteError("SPY_0DTE_PROVIDER_UNSUPPORTED") from exc

        SysConfig.enable_console_log(False)
        context = None
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            ret, chain = context.get_option_chain(
                SPY_CODE,
                start=session_date.isoformat(),
                end=session_date.isoformat(),
            )
            if ret != RET_OK or not hasattr(chain, "iterrows"):
                raise Spy0dteError("SPY_0DTE_CHAIN_UNAVAILABLE")
            metadata: dict[str, dict[str, Any]] = {}
            for _, row in chain.iterrows():
                try:
                    code = str(row["code"])
                    expiry = date.fromisoformat(str(row["strike_time"])[:10])
                    strike = float(row["strike_price"])
                    side = str(row["option_type"]).upper()
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    code.startswith(SPY_CODE)
                    and expiry == session_date
                    and strike > 0
                    and side in {"CALL", "PUT"}
                ):
                    metadata[code] = {"expiration": expiry, "strike": strike, "side": side}
            if not metadata:
                raise Spy0dteError("SPY_0DTE_CHAIN_UNAVAILABLE")

            snapshots: dict[str, dict[str, Any]] = {}
            codes = tuple(metadata)
            for offset in range(0, len(codes), 400):
                snap_ret, frame = context.get_market_snapshot(list(codes[offset : offset + 400]))
                if snap_ret != RET_OK or not hasattr(frame, "iterrows"):
                    raise Spy0dteError("SPY_0DTE_GREEKS_UNAVAILABLE")
                for _, row in frame.iterrows():
                    code = str(row.get("code") or "")
                    if code:
                        snapshots[code] = row.to_dict()

            history_ret, history, _ = context.request_history_kline(
                SPY_CODE,
                start=session_date.isoformat(),
                end=session_date.isoformat(),
                ktype=KLType.K_5M,
                autype=AuType.QFQ,
                max_count=1000,
            )
            if history_ret != RET_OK or not hasattr(history, "iterrows"):
                raise Spy0dteError("SPY_0DTE_INTRADAY_UNAVAILABLE")
            bars = self._bars(history, session_date)
            if len(bars) < 2:
                raise Spy0dteError("SPY_0DTE_INTRADAY_UNAVAILABLE")
            spot = bars[-1].close
            contracts = self._contracts(metadata, snapshots)
            if len(contracts) < 20:
                raise Spy0dteError("SPY_0DTE_MIN_COVERAGE_FAILURE")

            generated_at = datetime.now(UTC)
            calculation_time = bars[-1].timestamp_et
            volume_gex = build_gex_snapshot(
                "SPY", spot, contracts, calculation_time, exposure_basis="volume"
            )
            oi_gex = build_gex_snapshot(
                "SPY", spot, contracts, calculation_time, exposure_basis="open_interest"
            )
            vwap = self._vwap(bars)
            ema9 = self._ema9(bars)
            previous_volumes = [bar.volume for bar in bars[-21:-1] if bar.volume > 0]
            volume_ratio = (
                bars[-1].volume / (sum(previous_volumes) / len(previous_volumes))
                if bars[-1].volume > 0 and previous_volumes
                else None
            )
            recent_base = bars[-4].close if len(bars) >= 4 else bars[0].close
            recent_return = (spot / recent_base - 1) if recent_base > 0 else 0.0
            score = calculate_score(
                SpyScoreInputs(
                    gex=self._bounded(volume_gex.normalized_net_gex * 100),
                    price_structure=self._bounded(recent_return / 0.003 * 100),
                    vwap=self._bounded((spot / vwap - 1) / 0.002 * 100),
                    ema9=self._bounded((spot / ema9 - 1) / 0.0015 * 100),
                    volume=self._bounded(((volume_ratio or 1.0) - 1) * 50),
                    momentum=self._bounded(recent_return / 0.002 * 100),
                    key_level_position=(
                        50.0
                        if volume_gex.zero_gamma is not None and spot > volume_gex.zero_gamma
                        else -50.0
                        if volume_gex.zero_gamma is not None
                        else 0.0
                    ),
                ),
                policy,
                previous_display_score=previous_display_score,
            )
            supports = self._key_levels(
                (*volume_gex.major_support, *volume_gex.minor_support),
                bars,
                spot,
                vwap,
                ema9,
                below=True,
            )
            resistances = self._key_levels(
                (*volume_gex.major_resistance, *volume_gex.minor_resistance),
                bars,
                spot,
                vwap,
                ema9,
                below=False,
            )
            source_times = [bars[-1].timestamp_et]
            source_times.extend(
                timestamp
                for timestamp in (
                    self._timestamp(row.get("update_time")) for row in snapshots.values()
                )
                if timestamp is not None
            )
            return Spy0dteSnapshot(
                session_date=session_date,
                generated_at=generated_at,
                spot=spot,
                spot_timestamp=bars[-1].timestamp_et,
                raw_score=score.raw_score,
                display_score=score.display_score,
                structure_label=score.structure_label,
                gamma_regime=volume_gex.gamma_regime,
                net_gex=volume_gex.net_gex,
                gamma_flip=volume_gex.zero_gamma,
                gamma_magnet=volume_gex.gamma_magnet,
                call_wall=volume_gex.call_wall,
                put_wall=volume_gex.put_wall,
                supports=supports,
                resistances=resistances,
                vwap=vwap,
                ema9_5m=ema9,
                volume_ratio=volume_ratio,
                momentum=self._momentum(recent_return),
                volume_gamma_bias=self._gamma_bias(volume_gex.normalized_net_gex),
                oi_gamma_bias=self._gamma_bias(oi_gex.normalized_net_gex),
                expected_move=self._expected_move(metadata, snapshots, spot),
                option_contract_count=len(contracts),
                source_timestamp=max(source_times),
                provider="moomoo",
                stale=session_date != datetime.now(ET).date(),
                warnings=(),
                policy_version=policy.version,
                gex=volume_gex,
                bars=bars,
            )
        except Spy0dteError:
            raise
        except Exception as exc:
            raise Spy0dteError("SPY_0DTE_GENERATION_FAILED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()

    @staticmethod
    def _bars(frame: Any, session_date: date) -> tuple[GexIntradayBar, ...]:
        values: list[GexIntradayBar] = []
        for _, row in frame.iterrows():
            try:
                timestamp = datetime.strptime(
                    str(row["time_key"])[:19], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=ET)
                if timestamp.date() != session_date or not (
                    time(9, 30) <= timestamp.time() <= time(16, 0)
                ):
                    continue
                values.append(
                    GexIntradayBar(
                        timestamp,
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        max(0.0, float(row.get("volume") or 0)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(sorted(values, key=lambda item: item.timestamp_et))

    @classmethod
    def _contracts(
        cls,
        metadata: dict[str, dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
    ) -> tuple[GexOptionContract, ...]:
        contracts: list[GexOptionContract] = []
        for code, item in metadata.items():
            row = snapshots.get(code)
            if row is None:
                continue
            try:
                gamma = float(row["option_gamma"])
                iv = float(row["option_implied_volatility"])
                oi = int(row["option_open_interest"])
                volume = int(row["volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if gamma <= 0 or iv <= 0 or oi < 0 or volume < 0:
                continue
            contracts.append(
                GexOptionContract(
                    symbol=code,
                    expiration=item["expiration"],
                    strike=float(item["strike"]),
                    side=OptionSide(str(item["side"])),
                    open_interest=oi,
                    gamma=gamma,
                    implied_volatility=iv / 100,
                    volume=volume,
                )
            )
        return tuple(contracts)

    @staticmethod
    def _vwap(bars: tuple[GexIntradayBar, ...]) -> float:
        volume = sum(bar.volume for bar in bars)
        if volume <= 0:
            raise Spy0dteError("SPY_0DTE_VOLUME_UNAVAILABLE")
        return sum(((bar.high + bar.low + bar.close) / 3) * bar.volume for bar in bars) / volume

    @staticmethod
    def _ema9(bars: tuple[GexIntradayBar, ...]) -> float:
        value = bars[0].close
        for bar in bars[1:]:
            value = bar.close * 0.2 + value * 0.8
        return value

    @staticmethod
    def _bounded(value: float) -> float:
        return max(-100.0, min(100.0, value))

    @staticmethod
    def _gamma_bias(ratio: float) -> str:
        if ratio >= 0.25:
            return "明显偏多"
        if ratio >= 0.08:
            return "偏多"
        if ratio <= -0.25:
            return "明显偏空"
        if ratio <= -0.08:
            return "偏空"
        return "中性"

    @staticmethod
    def _momentum(value: float) -> str:
        if value >= 0.004:
            return "强"
        if value >= 0.001:
            return "偏强"
        if value <= -0.004:
            return "弱"
        if value <= -0.001:
            return "偏弱"
        return "中性"

    @staticmethod
    def _key_levels(
        levels: tuple[float, ...],
        bars: tuple[GexIntradayBar, ...],
        spot: float,
        vwap: float,
        ema9: float,
        *,
        below: bool,
    ) -> tuple[float, ...]:
        recent = bars[-20:]
        structural = (
            min(bar.low for bar in recent),
            min(bar.low for bar in bars),
        ) if below else (
            max(bar.high for bar in recent),
            max(bar.high for bar in bars),
        )
        candidates = (*levels, *structural, vwap, ema9)
        selected = {
            round(level, 2)
            for level in candidates
            if abs(level - spot) <= spot * 0.02
            and (level < spot if below else level > spot)
        }
        return tuple(sorted(selected, key=lambda level: abs(level - spot))[:2])

    @staticmethod
    def _expected_move(
        metadata: dict[str, dict[str, Any]], snapshots: dict[str, dict[str, Any]], spot: float
    ) -> float | None:
        strikes = sorted({float(item["strike"]) for item in metadata.values()})
        if not strikes:
            return None
        atm = min(strikes, key=lambda strike: abs(strike - spot))
        mids = []
        for code, item in metadata.items():
            if float(item["strike"]) != atm:
                continue
            row = snapshots.get(code) or {}
            try:
                bid, ask = float(row["bid_price"]), float(row["ask_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if bid >= 0 and ask > 0 and ask >= bid:
                mids.append((bid + ask) / 2)
        return sum(mids) if len(mids) == 2 else None

    @staticmethod
    def _timestamp(raw: object) -> datetime | None:
        if not isinstance(raw, str):
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            with suppress(ValueError):
                return datetime.strptime(raw, fmt).replace(tzinfo=ET)
        return None

    def _probe_sync(self, chain_session: date) -> SpyCapabilityReport:
        try:
            from moomoo import RET_OK, AuType, KLType, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise Spy0dteError("SPY_0DTE_PROVIDER_UNSUPPORTED") from exc

        SysConfig.enable_console_log(False)
        context = None
        checked_at = datetime.now(UTC)
        connected = False
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            connected = True
            ret, chain = context.get_option_chain(
                SPY_CODE,
                start=chain_session.isoformat(),
                end=chain_session.isoformat(),
            )
            rows = []
            if ret == RET_OK and hasattr(chain, "iterrows"):
                rows = [
                    row
                    for _, row in chain.iterrows()
                    if str(row.get("code") or "").startswith(SPY_CODE)
                    and str(row.get("strike_time") or "")[:10] == chain_session.isoformat()
                ]
            codes = [str(row.get("code")) for row in rows]
            sample = None
            if codes:
                middle = len(codes) // 2
                selected = codes[max(0, middle - 20) : middle + 20]
                snap_ret, frame = context.get_market_snapshot(selected)
                if snap_ret == RET_OK and hasattr(frame, "columns") and not frame.empty:
                    sample = frame

            spot_ret, spot_frame = context.get_market_snapshot([SPY_CODE])
            spot_ok = bool(
                spot_ret == RET_OK
                and hasattr(spot_frame, "empty")
                and not spot_frame.empty
                and float(spot_frame.iloc[0].get("last_price") or 0) > 0
            )
            spot = float(spot_frame.iloc[0].get("last_price")) if spot_ok else None
            history_ret, history_frame, _ = context.request_history_kline(
                SPY_CODE,
                start=chain_session.isoformat(),
                end=chain_session.isoformat(),
                ktype=KLType.K_5M,
                autype=AuType.NONE,
                max_count=1000,
            )
            bars_ok = bool(
                history_ret == RET_OK
                and hasattr(history_frame, "empty")
                and not history_frame.empty
            )
            bar_count = len(history_frame) if bars_ok else 0
            columns = set(sample.columns) if sample is not None else set()
            has_values = lambda name: bool(  # noqa: E731
                sample is not None and name in columns and sample[name].notna().any()
            )
            report = SpyCapabilityReport(
                checked_at=checked_at,
                chain_session=chain_session,
                opend_connected=connected,
                spy_chain=bool(rows),
                spy_only=bool(rows) and len(rows) == len(codes),
                contract_count=len(rows),
                gamma=has_values("option_gamma"),
                implied_volatility=has_values("option_implied_volatility"),
                open_interest=has_values("option_open_interest"),
                volume=has_values("volume"),
                bid_ask=has_values("bid_price") and has_values("ask_price"),
                timestamps=has_values("update_time"),
                spy_spot=spot_ok,
                spy_5m=bars_ok,
                spot=spot,
                bar_count=bar_count,
                error_code=(
                    None
                    if spot_ok and bars_ok and rows
                    else "SPY_0DTE_PROVIDER_UNSUPPORTED"
                    if not spot_ok or not bars_ok
                    else "SPY_0DTE_CHAIN_UNAVAILABLE"
                ),
            )
            return report
        except Spy0dteError:
            raise
        except Exception as exc:
            raise Spy0dteError("SPY_0DTE_PROVIDER_UNSUPPORTED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()


def render_capability_image(report: SpyCapabilityReport, policy: Spy0dtePolicy) -> bytes:
    """Render a deterministic TEST diagnostic image without fabricated market values."""

    from PIL import Image, ImageDraw, ImageFont

    def font(size: int, bold: bool = False):
        candidates = (
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf",
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                try:
                    return ImageFont.truetype(candidate, size=size)
                except OSError:
                    continue
        return ImageFont.load_default()

    image = Image.new("RGB", (1800, 1200), "#050807")
    draw = ImageDraw.Draw(image)
    draw.text((90, 70), "AXIS · SPY 0DTE", fill="#F4F5F1", font=font(56, True))
    draw.text((90, 145), "MOOMOO 实时能力门禁 · TEST", fill="#86F7A8", font=font(30, True))
    draw.line((90, 205, 1710, 205), fill="#24332E", width=2)

    checks = (
        ("OpenD 连接", report.opend_connected),
        ("真实 SPY 合约链", report.spy_chain and report.spy_only),
        (
            "Gamma / IV / OI / Volume",
            all((report.gamma, report.implied_volatility, report.open_interest, report.volume)),
        ),
        ("Bid / Ask / 时间戳", report.bid_ask and report.timestamps),
        ("SPY 现价", report.spy_spot),
        (f"SPY 5 分钟 K 线 · {report.bar_count} 根", report.spy_5m),
    )
    y = 270
    for label, passed in checks:
        color = "#86F7A8" if passed else "#E56B73"
        symbol = "✓" if passed else "×"
        draw.rounded_rectangle(
            (90, y, 1710, y + 100), radius=16, fill="#0A1210", outline="#23342E", width=2
        )
        draw.text((125, y + 25), symbol, fill=color, font=font(38, True))
        draw.text((190, y + 29), label, fill="#F4F5F1", font=font(28, True))
        draw.text((1380, y + 29), "通过" if passed else "不可用", fill=color, font=font(28, True))
        y += 115

    state = "能力门禁通过" if report.ready else "失败关闭 · 不生成市场结构评分"
    state_color = "#86F7A8" if report.ready else "#E6C84F"
    draw.text((90, 985), state, fill=state_color, font=font(36, True))
    draw.text(
        (90, 1045),
        (
            f"链日期 {report.chain_session:%Y-%m-%d} · "
            f"SPY 合约 {report.contract_count} · 策略 {policy.version}"
        ),
        fill="#A8B2AE",
        font=font(23),
    )
    draw.text(
        (90, 1090),
        "仅用于市场分析与教育，不构成投资建议、交易建议或买卖信号。",
        fill="#7F8B86",
        font=font(21),
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_snapshot_image(snapshot: Spy0dteSnapshot, policy: Spy0dtePolicy) -> bytes:
    """Render the frozen SPY snapshot without performing another market-data request."""

    return render_gex_heatmap(snapshot.gex, snapshot.bars, policy)


def latest_completed_session(now_et: datetime) -> date:
    """Return the latest completed weekday session for deterministic TEST probes."""

    local = now_et.astimezone(ET)
    candidate = local.date()
    if candidate.weekday() < 5 and local.timetz().replace(tzinfo=None) >= time(16, 0):
        return candidate
    candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def publishing_slot(
    now_et: datetime,
    policy: Spy0dtePolicy,
    calendar: Any,
) -> tuple[date, int, int] | None:
    local = now_et.astimezone(ET)
    session_date = local.date()
    if not calendar.is_trading_day(session_date):
        return None
    close = calendar.session_close(session_date).astimezone(ET)
    start_hour, start_minute = (int(part) for part in policy.start_time_et.split(":"))
    start = datetime.combine(session_date, time(start_hour, start_minute), tzinfo=ET)
    if local < start or local >= close or local.minute % policy.refresh_minutes:
        return None
    return session_date, local.hour, local.minute


def finite_score(value: float) -> bool:
    return math.isfinite(value) and -100 <= value <= 100
