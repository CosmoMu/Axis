from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.integrations.massive_market_data import MarketDataProviderError, MarketPriceRequest
from app.integrations.moomoo_market_data import (
    MarketDataError,
    MoomooMarketDataClient,
    MoomooOptionMarketDataProvider,
    MoomooOptionOrderBookProvider,
    OptionQuoteRequest,
    _quote_time,
    moomoo_option_code,
    normalize_us_underlying,
)


class FakeRow(dict[str, object]):
    pass


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def iterrows(self):  # type: ignore[no-untyped-def]
        for index, row in enumerate(self.rows):
            yield index, FakeRow(row)


class FakeContext:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def get_option_chain(self, *args: object, **kwargs: object) -> tuple[int, FakeFrame]:
        return 0, FakeFrame(self.rows)


def request() -> OptionQuoteRequest:
    return OptionQuoteRequest(
        key="trade-1",
        ticker="$aapl",
        expiry=date(2026, 9, 18),
        strike=Decimal("200"),
        option_side="CALL",
    )


def test_us_underlying_normalization_is_strict() -> None:
    assert normalize_us_underlying("$aapl") == "US.AAPL"
    assert normalize_us_underlying("US.SPY") == "US.SPY"
    with pytest.raises(MarketDataError, match="ONLY_US_OPTIONS_SUPPORTED"):
        normalize_us_underlying("HK.00700")


def test_moomoo_snapshot_time_accepts_fractional_seconds() -> None:
    parsed = _quote_time("2026-08-28 20:02:33.982")
    assert parsed is not None
    assert parsed.isoformat() == "2026-08-28T20:02:33.982000-04:00"


def test_canonical_occ_tickers_translate_to_moomoo_codes() -> None:
    assert (
        moomoo_option_code("O:QQQ260904C00717000")
        == "US.QQQ260904C717000"
    )
    assert (
        moomoo_option_code("O:SPXW260902C07670000")
        == "US.SPXW260902C7670000"
    )
    with pytest.raises(MarketDataProviderError, match="OPTION_CONTRACT_INVALID"):
        moomoo_option_code("US.QQQ260904C717000")


def test_tracking_snapshot_uses_mid_and_preserves_canonical_ticker() -> None:
    provider = MoomooOptionMarketDataProvider(
        host="127.0.0.1",
        port=11111,
        price_source="MID",
        max_quote_age_seconds=120,
        last_trade_quote_guard_pct=Decimal("50"),
    )
    request = MarketPriceRequest("ST-0001", "QQQ", "O:QQQ260904C00717000")

    quote = provider._normalize_tracking_snapshot(
        request,
        {
            "bid_price": "0.88",
            "ask_price": "0.90",
            "last_price": "0.89",
            "update_time": "2026-09-02 11:08:37",
        },
        received_at=datetime(2026, 9, 2, 15, 9, tzinfo=UTC),
        market_status="MORNING",
    )

    assert quote.option_ticker == "O:QQQ260904C00717000"
    assert quote.price == Decimal("0.89")
    assert quote.source_timestamp.isoformat() == "2026-09-02T11:08:37-04:00"


def test_tracking_snapshot_rejects_stale_moomoo_time() -> None:
    provider = MoomooOptionMarketDataProvider(
        host="127.0.0.1",
        port=11111,
        price_source="MID",
        max_quote_age_seconds=30,
        last_trade_quote_guard_pct=Decimal("50"),
    )
    request = MarketPriceRequest("ST-0001", "QQQ", "O:QQQ260904C00717000")

    with pytest.raises(MarketDataProviderError, match="MOOMOO_QUOTE_STALE"):
        provider._normalize_tracking_snapshot(
            request,
            {
                "bid_price": "0.88",
                "ask_price": "0.90",
                "last_price": "0.89",
                "update_time": "2026-09-02 11:08:00",
            },
            received_at=datetime(2026, 9, 2, 15, 9, tzinfo=UTC),
            market_status="MORNING",
        )


def test_order_book_payload_requires_server_timestamp() -> None:
    payload = {
        "code": "US.SPXW260902C7670000",
        "Bid": [[10.1, 2.0, 1, {}]],
        "Ask": [[10.3, 4.0, 1, {}]],
        "svr_recv_time_bid": "2026-09-02 11:39:35.924",
        "svr_recv_time_ask": "2026-09-02 11:39:35.924",
    }

    normalized = MoomooOptionOrderBookProvider._normalize_order_book_payload(payload)

    assert normalized is not None
    code, bid, ask, timestamp = normalized
    assert code == "US.SPXW260902C7670000"
    assert bid == Decimal("10.1")
    assert ask == Decimal("10.3")
    assert timestamp.isoformat() == "2026-09-02T11:39:35.924000-04:00"
    assert (
        MoomooOptionOrderBookProvider._normalize_order_book_payload(
            {**payload, "svr_recv_time_bid": "", "svr_recv_time_ask": ""}
        )
        is None
    )


@pytest.mark.asyncio
async def test_order_book_provider_returns_mid_from_fresh_push() -> None:
    provider = MoomooOptionOrderBookProvider(
        host="127.0.0.1",
        port=11111,
        price_source="MID",
        max_quote_age_seconds=120,
    )
    request = MarketPriceRequest("ST-0001", "SPX", "O:SPXW260902C07670000")
    code = moomoo_option_code(request.option_ticker)
    now = datetime.now(UTC)
    provider._codes.add(code)
    provider._books[code] = (
        Decimal("10.1"),
        Decimal("10.3"),
        now,
        now,
    )

    quote = (await provider.fetch_prices((request,)))[0]

    assert quote.price == Decimal("10.2")
    assert quote.market_status == "ORDER_BOOK_PUSH"


def test_option_contract_is_resolved_from_exact_chain_match() -> None:
    context = FakeContext(
        [
            {
                "code": "US.AAPL260918C200000",
                "strike_time": "2026-09-18",
                "strike_price": 200.0,
                "option_type": "CALL",
            },
            {
                "code": "US.AAPL260918P200000",
                "strike_time": "2026-09-18",
                "strike_price": 200.0,
                "option_type": "PUT",
            },
        ]
    )
    code = MoomooMarketDataClient._resolve_option_code(
        context,
        request(),
        option_type="CALL",
        ret_ok=0,
    )
    assert code == "US.AAPL260918C200000"


def test_option_contract_resolution_rejects_missing_or_ambiguous_matches() -> None:
    with pytest.raises(MarketDataError, match="OPTION_CONTRACT_NOT_FOUND"):
        MoomooMarketDataClient._resolve_option_code(
            FakeContext([]), request(), option_type="CALL", ret_ok=0
        )

    duplicate = {
        "strike_time": "2026-09-18",
        "strike_price": 200,
        "option_type": "CALL",
    }
    with pytest.raises(MarketDataError, match="OPTION_CONTRACT_AMBIGUOUS"):
        MoomooMarketDataClient._resolve_option_code(
            FakeContext(
                [
                    {**duplicate, "code": "US.ONE"},
                    {**duplicate, "code": "US.TWO"},
                ]
            ),
            request(),
            option_type="CALL",
            ret_ok=0,
        )
