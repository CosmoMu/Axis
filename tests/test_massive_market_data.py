import ssl
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.integrations.massive_market_data import (
    MarketDataProviderError,
    MarketPriceRequest,
    MassiveMarketDataProvider,
    massive_option_ticker,
    massive_underlying_ticker,
    verified_ssl_context,
)


class FakeResponse:
    def __init__(self, payload: dict, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self, *, content_type: object = None) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> FakeResponse:
        self.calls.append((url, params))
        return self.responses.pop(0)


def provider(price_source: str) -> MassiveMarketDataProvider:
    return MassiveMarketDataProvider(
        api_key="test-only",
        price_source=price_source,
        max_quote_age_seconds=120,
        last_trade_quote_guard_pct=50,
    )


def payload(*, bid: str = "1.10", ask: str = "1.30", last: str = "1.20") -> dict:
    now_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    return {
        "results": {
            "details": {"ticker": "O:NVDA260831C00500000"},
            "last_quote": {
                "bid": bid,
                "ask": ask,
                "midpoint": "1.20",
                "last_updated": now_ns,
            },
            "last_trade": {"price": last, "sip_timestamp": now_ns},
            "market_status": "open",
        }
    }


def test_massive_contract_and_price_source_are_normalized() -> None:
    ticker = massive_option_ticker("nvda", date(2026, 8, 31), Decimal("500"), "CALL")
    assert ticker == "O:NVDA260831C00500000"
    request = MarketPriceRequest("key", "NVDA", ticker)

    bid = provider("BID")._normalize(request, payload())
    mid = provider("MID")._normalize(request, payload())
    last = provider("LAST")._normalize(request, payload())

    assert bid.price == Decimal("1.10") and bid.price_source == "BID"
    assert mid.price == Decimal("1.20") and mid.price_source == "MID"
    assert last.price == Decimal("1.20") and last.price_source == "LAST"


def test_outlier_last_print_cannot_pollute_tracking_price() -> None:
    request = MarketPriceRequest("key", "NVDA", "O:NVDA260831C00500000")
    with pytest.raises(MarketDataProviderError, match="LAST_TRADE_OUTLIER"):
        provider("LAST")._normalize(request, payload(last="5.00"))


def test_massive_uses_a_verified_bundled_ca_store() -> None:
    context = verified_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0


def test_massive_option_contract_reference_is_normalized() -> None:
    normalized = provider("BID")._normalize_contract(
        {
            "ticker": "O:RIVN261016C00018000",
            "underlying_ticker": "RIVN",
            "expiration_date": "2026-10-16",
            "strike_price": 18,
            "contract_type": "call",
        }
    )

    assert normalized is not None
    assert normalized.ticker == "O:RIVN261016C00018000"
    assert normalized.expiry == date(2026, 10, 16)
    assert normalized.strike == Decimal("18")
    assert normalized.option_side == "CALL"


def test_massive_maps_spxw_contract_root_to_spx_underlying() -> None:
    assert massive_underlying_ticker("SPXW") == "SPX"
    assert massive_underlying_ticker("$spxw") == "SPX"
    assert massive_underlying_ticker("US.NVDA") == "NVDA"
    assert (
        massive_option_ticker("SPXW", date(2026, 9, 1), Decimal("7655"), "PUT")
        == "O:SPXW260901P07655000"
    )


@pytest.mark.asyncio
async def test_spxw_reference_lookup_uses_spx_but_preserves_contract_root() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "results": [
                        {
                            "ticker": "O:SPXW260901P07655000",
                            "underlying_ticker": "SPX",
                            "expiration_date": "2026-09-01",
                            "strike_price": 7655,
                            "contract_type": "put",
                        }
                    ]
                }
            )
        ]
    )
    market = MassiveMarketDataProvider(
        api_key="test-only",
        price_source="MID",
        max_quote_age_seconds=120,
        last_trade_quote_guard_pct=Decimal("50"),
        session=session,  # type: ignore[arg-type]
    )

    contracts = await market.list_option_contracts(
        underlying="SPXW",
        start=date(2026, 9, 1),
        end=date(2026, 9, 1),
        strike=Decimal("7655"),
        option_side="PUT",
    )

    assert session.calls[0][1] is not None
    assert session.calls[0][1]["underlying_ticker"] == "SPX"
    assert contracts[0].ticker == "O:SPXW260901P07655000"


@pytest.mark.asyncio
async def test_spxw_snapshot_lookup_uses_spx_underlying_path() -> None:
    session = FakeSession([FakeResponse(payload())])
    market = MassiveMarketDataProvider(
        api_key="test-only",
        price_source="MID",
        max_quote_age_seconds=120,
        last_trade_quote_guard_pct=Decimal("50"),
        session=session,  # type: ignore[arg-type]
    )

    prices = await market.fetch_prices(
        (
            MarketPriceRequest(
                "key",
                "SPXW",
                "O:SPXW260901P07655000",
            ),
        )
    )

    assert "/v3/snapshot/options/SPX/O:SPXW260901P07655000" in session.calls[0][0]
    assert prices[0].price == Decimal("1.20")
