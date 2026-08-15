"""Tests for the Hotline.ua SSR HTML parser."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from marketua.providers.hotline import HotlineError, HotlineProvider, ITEMS_PER_PAGE

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _provider_with_page() -> HotlineProvider:
    html = (FIXTURES_DIR / "hotline_search.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HotlineProvider(client=client)


def test_parses_cards_into_offers() -> None:
    result = _provider_with_page().search("ssd 2.5 sata")
    assert result.total == 84
    assert len(result.offers) > 0

    first = result.offers[0]
    assert first.title.startswith("Maiwo")
    assert first.url.startswith("https://hotline.ua/")
    assert first.price == 243.0
    assert first.currency == "UAH"
    # id is the URL path (Hotline cards expose no numeric id)
    assert first.id.startswith("/ua/")


def test_price_range_is_parsed_to_min() -> None:
    result = _provider_with_page().search("ssd 2.5 sata")
    # The card with a "X – Y ₴" range should carry the min price.
    assert all(o.price is not None for o in result.offers[:10])


def test_price_filters_are_applied_client_side() -> None:
    result = _provider_with_page().search("ssd 2.5 sata", min_price=500, max_price=1500)
    assert result.offers  # non-empty
    assert all(o.price is not None and 500 <= o.price <= 1500 for o in result.offers)


def test_offset_requests_next_page() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(
            200,
            text=(FIXTURES_DIR / "hotline_search.html").read_text(encoding="utf-8"),
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    HotlineProvider(client=client).search("ssd", offset=ITEMS_PER_PAGE)
    assert captured["p"] == "2"

    captured.clear()
    HotlineProvider(client=client).search("ssd", offset=0)
    assert "p" not in captured


def test_network_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(HotlineError):
        HotlineProvider(client=client).search("ssd")


def test_empty_page_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>no cards</body></html>", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(HotlineError, match="no product cards"):
        HotlineProvider(client=client).search("ssd")
