"""AXIS SPXW 0DTE market-structure desk (Moomoo-only, fail closed)."""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ET = ZoneInfo("America/New_York")
SPX_CHAIN_OWNER = "US..SPX"
SPXW_CODE_PREFIX = "US.SPXW"


class Spxw0dteError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Spxw0dtePolicy:
    version: str
    enabled: bool
    mode: str
    start_time_et: str
    end_time_et: str
    refresh_minutes: int
    smoothing_current: float
    weights: dict[str, float]

    @classmethod
    def load(cls, path: Path) -> Spxw0dtePolicy:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise Spxw0dteError("SPXW_0DTE_POLICY_INVALID")
        score = payload.get("score")
        smoothing = payload.get("smoothing")
        if not isinstance(score, dict) or not isinstance(smoothing, dict):
            raise Spxw0dteError("SPXW_0DTE_POLICY_INVALID")
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
            raise Spxw0dteError("SPXW_0DTE_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class SpxwCapabilityReport:
    checked_at: datetime
    chain_session: date
    opend_connected: bool
    spxw_chain: bool
    spxw_only: bool
    contract_count: int
    gamma: bool
    implied_volatility: bool
    open_interest: bool
    volume: bool
    bid_ask: bool
    timestamps: bool
    spx_spot: bool
    spx_5m: bool
    error_code: str | None
    provider: str = "moomoo"

    @property
    def ready(self) -> bool:
        return all(
            (
                self.opend_connected,
                self.spxw_chain,
                self.spxw_only,
                self.gamma,
                self.implied_volatility,
                self.open_interest,
                self.volume,
                self.bid_ask,
                self.timestamps,
                self.spx_spot,
                self.spx_5m,
            )
        )


@dataclass(frozen=True, slots=True)
class SpxwScoreInputs:
    gex: float
    price_structure: float
    vwap: float
    ema9: float
    volume: float
    momentum: float
    key_level_position: float


@dataclass(frozen=True, slots=True)
class SpxwScore:
    raw_score: int
    display_score: int
    structure_label: str


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
    inputs: SpxwScoreInputs,
    policy: Spxw0dtePolicy,
    *,
    previous_display_score: int | None = None,
) -> SpxwScore:
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
    return SpxwScore(raw, display, structure_label(display))


class MoomooSpxw0dteProvider:
    """Read-only capability and data boundary for real SPXW contracts.

    Moomoo exposes SPXW contracts through the ``US..SPX`` chain-owner code.
    Every returned option is independently filtered by its real ``US.SPXW``
    contract root and exact expiration date. No SPY proxy is permitted.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    async def probe(self, chain_session: date) -> SpxwCapabilityReport:
        return await asyncio.to_thread(self._probe_sync, chain_session)

    def _probe_sync(self, chain_session: date) -> SpxwCapabilityReport:
        try:
            from moomoo import RET_OK, AuType, KLType, OpenQuoteContext, SysConfig
        except Exception as exc:
            raise Spxw0dteError("SPXW_0DTE_PROVIDER_UNSUPPORTED") from exc

        SysConfig.enable_console_log(False)
        context = None
        checked_at = datetime.now(UTC)
        connected = False
        try:
            context = OpenQuoteContext(host=self.host, port=self.port)
            connected = True
            ret, chain = context.get_option_chain(
                SPX_CHAIN_OWNER,
                start=chain_session.isoformat(),
                end=chain_session.isoformat(),
            )
            rows = []
            if ret == RET_OK and hasattr(chain, "iterrows"):
                rows = [
                    row
                    for _, row in chain.iterrows()
                    if str(row.get("code") or "").startswith(SPXW_CODE_PREFIX)
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

            spot_ret, spot_frame = context.get_market_snapshot([SPX_CHAIN_OWNER])
            spot_ok = bool(
                spot_ret == RET_OK
                and hasattr(spot_frame, "empty")
                and not spot_frame.empty
                and float(spot_frame.iloc[0].get("last_price") or 0) > 0
            )
            history_ret, history_frame, _ = context.request_history_kline(
                SPX_CHAIN_OWNER,
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
            columns = set(sample.columns) if sample is not None else set()
            has_values = lambda name: bool(  # noqa: E731
                sample is not None and name in columns and sample[name].notna().any()
            )
            report = SpxwCapabilityReport(
                checked_at=checked_at,
                chain_session=chain_session,
                opend_connected=connected,
                spxw_chain=bool(rows),
                spxw_only=bool(rows) and len(rows) == len(codes),
                contract_count=len(rows),
                gamma=has_values("option_gamma"),
                implied_volatility=has_values("option_implied_volatility"),
                open_interest=has_values("option_open_interest"),
                volume=has_values("volume"),
                bid_ask=has_values("bid_price") and has_values("ask_price"),
                timestamps=has_values("update_time"),
                spx_spot=spot_ok,
                spx_5m=bars_ok,
                error_code=(
                    None
                    if spot_ok and bars_ok and rows
                    else "SPXW_0DTE_PROVIDER_UNSUPPORTED"
                    if not spot_ok or not bars_ok
                    else "SPXW_0DTE_CHAIN_UNAVAILABLE"
                ),
            )
            return report
        except Spxw0dteError:
            raise
        except Exception as exc:
            raise Spxw0dteError("SPXW_0DTE_PROVIDER_UNSUPPORTED") from exc
        finally:
            if context is not None:
                with suppress(Exception):
                    context.close()


def render_capability_image(report: SpxwCapabilityReport, policy: Spxw0dtePolicy) -> bytes:
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
    draw.text((90, 70), "AXIS · SPXW 0DTE", fill="#F4F5F1", font=font(56, True))
    draw.text((90, 145), "MOOMOO 实时能力门禁 · TEST", fill="#86F7A8", font=font(30, True))
    draw.line((90, 205, 1710, 205), fill="#24332E", width=2)

    checks = (
        ("OpenD 连接", report.opend_connected),
        ("真实 SPXW 合约链", report.spxw_chain and report.spxw_only),
        (
            "Gamma / IV / OI / Volume",
            all((report.gamma, report.implied_volatility, report.open_interest, report.volume)),
        ),
        ("Bid / Ask / 时间戳", report.bid_ask and report.timestamps),
        ("SPX 指数现价", report.spx_spot),
        ("SPX 5 分钟 K 线", report.spx_5m),
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
            f"SPXW 合约 {report.contract_count} · 策略 {policy.version}"
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


def next_weekday(value: date) -> date:
    candidate = value
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def finite_score(value: float) -> bool:
    return math.isfinite(value) and -100 <= value <= 100
