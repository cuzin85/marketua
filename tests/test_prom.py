"""Tests for the Prom.ua JSON-LD parser."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from marketua.providers.prom import ITEMS_PER_PAGE, PromError, PromProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _provider_with_page() -> PromProvider:
    html = (FIXTURES_DIR / "prom_search.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PromProvider(client=client)


def test_parses_products_into_offers() -> None:
    result = _provider_with_page().search("ssd 2.5")
    assert result.total == 6513
    assert len(result.offers) == 10

    first = result.offers[0]
    assert first.id == "8634975113066207435"
    assert first.title == "Накопичувач SSD 2.5\" 256GB Acer (RE100-25-256GB)"  # &quot; unescaped
    assert first.url.startswith("https://prom.ua/ua/")
    assert first.price == 1500.0
    assert first.currency == "UAH"


def test_price_filters_are_applied_client_side() -> None:
    result = _provider_with_page().search("ssd 2.5", min_price=1000, max_price=1800)
    assert result.offers
    assert all(o.price is not None and 1000 <= o.price <= 1800 for o in result.offers)


def test_offset_requests_next_page() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(
            200,
            text=(FIXTURES_DIR / "prom_search.html").read_text(encoding="utf-8"),
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    PromProvider(client=client).search("ssd", offset=ITEMS_PER_PAGE)
    assert captured["page"] == "2"

    captured.clear()
    PromProvider(client=client).search("ssd", offset=0)
    assert "page" not in captured


def test_network_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PromError):
        PromProvider(client=client).search("ssd")


def test_no_products_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>empty</body></html>", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PromError, match="no product JSON-LD"):
        PromProvider(client=client).search("ssd")
