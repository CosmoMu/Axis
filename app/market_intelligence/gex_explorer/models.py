"""Provider-independent models for AXIS GEX Explorer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class OptionSide(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True, slots=True)
class GexIntradayBar:
    timestamp_et: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp_et.tzinfo is None:
            raise ValueError("timestamp_et must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("intraday prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("intraday high/low must contain open and close")


@dataclass(frozen=True, slots=True)
class GexOptionContract:
    symbol: str
    expiration: date
    strike: float
    side: OptionSide
    open_interest: int | None
    gamma: float | None = None
    implied_volatility: float | None = None
    volume: int | None = None


@dataclass(frozen=True, slots=True)
class GexByStrike:
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float


@dataclass(frozen=True, slots=True)
class GexExpiration:
    expiration: date
    net_gex: float
    total_abs_gex: float
    call_wall: float | None
    put_wall: float | None
    included_contracts: int
    by_strike: tuple[GexByStrike, ...]


@dataclass(frozen=True, slots=True)
class GexZone:
    lower: float
    upper: float
    peak: float
    exposure: float


@dataclass(frozen=True, slots=True)
class GexTrigger:
    level: float | None
    target: float | None
    description: str


@dataclass(frozen=True, slots=True)
class GexSnapshot:
    ticker: str
    timestamp_et: datetime
    spot: float
    expirations: tuple[GexExpiration, ...]
    by_strike: tuple[GexByStrike, ...]
    net_gex: float
    total_abs_gex: float
    normalized_net_gex: float
    zero_gamma: float | None
    call_wall: float | None
    put_wall: float | None
    gamma_regime: str
    current_bias: str
    bullish_trigger: float | None
    bearish_trigger: float | None
    analysis_zh: tuple[str, str, str]
    gamma_method: str
    included_contracts: int
    skipped_contracts: int
    data_warnings: tuple[str, ...]
    dealer_sign_assumption: str
    exposure_basis: str = "open_interest"
    upper_magnet: float | None = None
    secondary_upper_magnet: float | None = None
    lower_magnet: float | None = None
    secondary_lower_magnet: float | None = None
    positive_gex: float = 0.0
    negative_gex: float = 0.0
    near_term_expiration: date | None = None
    near_term_net_gex: float = 0.0
    near_term_regime: str = "Gamma 平衡区"
    positive_zones: tuple[GexZone, ...] = ()
    negative_zones: tuple[GexZone, ...] = ()
    bullish: GexTrigger = GexTrigger(None, None, "暂无明确向上触发")
    bearish: GexTrigger = GexTrigger(None, None, "暂无明确向下触发")

    def __post_init__(self) -> None:
        if self.timestamp_et.tzinfo is None:
            raise ValueError("timestamp_et must be timezone-aware")
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        if not self.expirations:
            raise ValueError("at least one expiration is required")
