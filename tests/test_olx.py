"""Tests for OLX response parsing.

Uses a recorded-style fixture so parsing can be verified offline — the
Codespace's datacenter IP is blocked by OLX's CloudFront (403), so live
requests are not possible here.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from marketua.models import Offer
from marketua.providers.olx import OLXError, OLXProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FIXTURE = {
    "data": [
        {
            "id": 809230312,
            "url": "https://www.olx.ua/d/uk/obyavlenie/ssd-240gb-ID809230312.html",
            "title": "SSD 240GB Kingston A400",
            "params": [
                {
                    "key": "price",
                    "type": "price",
                    "value": {
                        "key": "price",
                        "value": "450",
                        "currency": "UAH",
                        "label": "Ціна",
                    },
                },
                {
                    "key": "state",
                    "value": {"key": "state", "value": "used", "label": "Стан"},
                },
            ],
            "location": {
                "city": {"id": 16, "name": "Київ"},
                "region": {"id": 1, "name": "Київська область"},
            },
        },
        {
            "id": 809230313,
            "url": "https://www.olx.ua/d/uk/obyavlenie/ssd-480gb-ID809230313.html",
            "title": "SSD 480GB Samsung 870 EVO",
            "params": [
                {"key": "price", "value": {"key": "price", "value": "1 200", "currency": "UAH"}}
            ],
            "location": {
                "city": {"id": 19, "name": "Львів"},
                "region": {"id": 14, "name": "Львівська область"},
            },
        },
        {
            "id": 809230314,
            "url": "https://www.olx.ua/d/uk/obyavlenie/ssd-1tb-ID809230314.html",
            "title": "SSD 1TB (торг)",
            # No price -> price on request / auction.
            "params": [],
            "location": {"region": {"id": 14, "name": "Львівська область"}},
        },
    ],
    "metadata": {"total_elements": 3},
}


def _provider_with_fixture(payload: dict) -> OLXProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OLXProvider(client=client)


def test_parses_offers_into_normalised_structure() -> None:
    provider = _provider_with_fixture(FIXTURE)
    offers = provider.search("ssd").offers

    assert len(offers) == 3

    first = offers[0]
    assert first == Offer(
        id="809230312",
        title="SSD 240GB Kingston A400",
        url="https://www.olx.ua/d/uk/obyavlenie/ssd-240gb-ID809230312.html",
        price=450.0,
        currency="UAH",
        location="Київ",
    )


def test_price_with_thousands_separator_is_normalised() -> None:
    offers = _provider_with_fixture(FIXTURE).search("ssd").offers
    assert offers[1].price == 1200.0
    assert offers[1].currency == "UAH"


def test_missing_price_and_city_are_handled() -> None:
    offers = _provider_with_fixture(FIXTURE).search("ssd").offers
    assert offers[2].price is None
    assert offers[2].currency is None
    # Falls back to region when no city is present.
    assert offers[2].location == "Львівська область"


def test_query_params_are_sent_to_api() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OLXProvider(client=client).search(
        "ssd",
        min_price=100,
        max_price=1500,
        region_id=16,
        city_id=268,
        category_id=458,
        state="used",
        filters={"capacity": [120, 560], "resolution": "full_hd"},
        limit=50,
    )

    assert captured["query"] == "ssd"
    # OLX's real param names differ from the friendly tool args.
    assert captured["filter_float_price:from"] == "100"
    assert captured["filter_float_price:to"] == "1500"
    assert captured["filter_float_capacity:from"] == "120"
    assert captured["filter_float_capacity:to"] == "560"
    assert captured["filter_enum_resolution"] == "full_hd"
    assert captured["region_id"] == "16"
    assert captured["city_id"] == "268"
    assert captured["category_id"] == "458"
    assert captured["filter_enum_state"] == "used"
    assert captured["limit"] == "50"


def test_filters_accept_olx_item_wrapper_for_ranges() -> None:
    """Models sometimes wrap a range in {"item": [from, to]} — normalize it."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OLXProvider(client=client).search(
        "монітор",
        filters={"screen_size": {"item": ["24", "24"]}},
    )

    assert captured["filter_float_screen_size:from"] == "24"
    assert captured["filter_float_screen_size:to"] == "24"


def test_search_warns_when_category_id_is_stale() -> None:
    """A dead/renumbered category id shows up as mismatched ids in the page."""
    payload = {
        "data": [
            {
                "id": 1,
                "title": "Ноутбук",
                "url": "u1",
                "category": {"id": 80},
            },
            {
                "id": 2,
                "title": "Комп'ютер",
                "url": "u2",
                "category": {"id": 78},
            },
        ],
        "metadata": {"total_elements": 2},
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload, request=r)
        )
    )
    result = OLXProvider(client=client).search("x", category_id=83)

    assert result.searched_category == {"id": 83, "name": "Монітори"}
    assert result.category_warning is not None
    assert "83" in result.category_warning
    # Offers carry the real category so the model can see the mismatch.
    assert {o.category_id for o in result.offers} == {80, 78}


def test_dead_category_id_is_rejected_with_hint() -> None:
    """OLX itself 400s a dead category id — surface a helpful hint."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={}, request=r)
        )
    )
    with pytest.raises(OLXError) as excinfo:
        OLXProvider(client=client).search("монітор", category_id=99999999)
    assert "stale" in str(excinfo.value)
    assert "list_categories" in str(excinfo.value)


def test_search_no_warning_when_category_matches() -> None:
    payload = {
        "data": [
            {
                "id": 1,
                "title": "Монітор",
                "url": "u1",
                "category": {"id": 83},
            }
        ],
        "metadata": {"total_elements": 1},
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload, request=r)
        )
    )
    result = OLXProvider(client=client).search("монітор", category_id=83)

    assert result.searched_category == {"id": 83, "name": "Монітори"}
    assert result.category_warning is None


def test_limit_is_clamped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OLXProvider(client=client).search("ssd", limit=999)


def test_http_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).search("ssd").offers


def test_non_json_response_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>blocked</html>", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).search("ssd").offers


def test_missing_data_field_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "nope"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).search("ssd").offers


def test_arranged_price_still_parses() -> None:
    """'Договірна' offers still carry a numeric asking price."""
    payload = {
        "data": [
            {
                "id": "1",
                "title": "SSD 240",
                "url": "https://example.com/1",
                "params": [
                    {
                        "key": "price",
                        "value": {
                            "value": 850,
                            "type": "arranged",
                            "arranged": True,
                            "currency": "UAH",
                            "label": "850 грн.",
                        },
                    }
                ],
                "location": {"city": {"name": "Черкаси"}},
            }
        ]
    }
    offers = _provider_with_fixture(payload).search("ssd").offers
    assert offers[0].price == 850.0
    assert offers[0].currency == "UAH"


def test_price_drop_uses_current_value() -> None:
    """A reduced price (previous_value) must not shadow the current one."""
    payload = {
        "data": [
            {
                "id": "1",
                "title": "SSD 256",
                "url": "https://example.com/1",
                "params": [
                    {
                        "key": "price",
                        "value": {
                            "value": 900,
                            "previous_value": 1000,
                            "currency": "UAH",
                            "label": "900 грн.",
                            "previous_label": "1 000 грн.",
                        },
                    }
                ],
                "location": {"city": {"name": "Вінниця"}},
            }
        ]
    }
    offers = _provider_with_fixture(payload).search("ssd").offers
    assert offers[0].price == 900.0


def test_missing_location_is_none() -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "title": "SSD",
                "url": "https://example.com/1",
                "params": [
                    {"key": "price", "value": {"value": 100, "currency": "UAH"}}
                ],
            }
        ]
    }
    offers = _provider_with_fixture(payload).search("ssd").offers
    assert offers[0].location is None


def test_empty_data_returns_empty_list() -> None:
    offers = _provider_with_fixture({"data": []}).search("ssd").offers
    assert offers == []


def test_timeout_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).search("ssd").offers


def test_invalid_state_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError, match="Invalid state"):
        OLXProvider(client=client).search("ssd", state="broken")


def test_discover_filters_aggregates_params() -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "title": "Monitor",
                "url": "https://example.com/1",
                "params": [
                    {"key": "price", "value": {"value": 800, "currency": "UAH"}},
                    {"key": "state", "value": {"key": "used", "label": "Вживане"}},
                    {
                        "key": "resolution",
                        "name": "Роздільна здатність",
                        "type": "select",
                        "value": {"key": "full_hd", "label": "1920x1080 (Full HD)"},
                    },
                    {
                        "key": "screen_type",
                        "name": "Тип екрану",
                        "type": "select",
                        "value": {"key": "ips", "label": "IPS"},
                    },
                ],
                "location": {"city": {"name": "Київ"}},
            },
            {
                "id": "2",
                "title": "Monitor 2",
                "url": "https://example.com/2",
                "params": [
                    {"key": "price", "value": {"value": 1200, "currency": "UAH"}},
                    {
                        "key": "resolution",
                        "name": "Роздільна здатність",
                        "type": "select",
                        "value": {"key": "qhd", "label": "2560x1440 (QHD)"},
                    },
                    {
                        "key": "diagonal",
                        "name": "Діагональ",
                        "type": "input",
                        "value": {"key": "27", "label": "27 \""},
                    },
                ],
                "location": {"city": {"name": "Львів"}},
            },
        ]
    }
    filters = _provider_with_fixture(payload).discover_filters("monitor")

    keys = {f["key"]: f for f in filters}
    assert set(keys) == {"resolution", "screen_type", "diagonal"}
    assert keys["resolution"]["kind"] == "enum"
    assert {v["key"] for v in keys["resolution"]["values"]} == {"full_hd", "qhd"}
    assert keys["diagonal"]["kind"] == "range"
    # price and state are universal/named -> excluded from discovery
    assert "price" not in keys and "state" not in keys


def test_discover_filters_passes_category_id() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["category_id"] = request.url.params.get("category_id")
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OLXProvider(client=client).discover_filters("монітор", category_id=83)
    assert captured["category_id"] == "83"

    captured.clear()
    OLXProvider(client=client).discover_filters("монітор")
    assert captured.get("category_id") is None


def test_sort_newest_maps_to_olx_param() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OLXProvider(client=client).search("монітор", sort="newest")
    assert captured["sort_by"] == "created_at:desc"

    captured.clear()
    OLXProvider(client=client).search("монітор", sort="price_asc")
    assert "sort_by" not in captured


def test_invalid_sort_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError, match="Invalid sort"):
        OLXProvider(client=client).search("монітор", sort="cheapest")


def test_price_sort_orders_offers_client_side() -> None:
    payload = {
        "data": [
            {"id": "1", "title": "a", "url": "u1", "params": [{"key": "price", "value": {"value": 1200}}]},
            {"id": "2", "title": "b", "url": "u2", "params": [{"key": "price", "value": {"value": 450}}]},
            {"id": "3", "title": "c", "url": "u3", "params": []},
            {"id": "4", "title": "d", "url": "u4", "params": [{"key": "price", "value": {"value": 800}}]},
        ]
    }

    asc = _provider_with_fixture(payload).search("монітор", sort="price_asc").offers
    assert [o.id for o in asc] == ["2", "4", "1", "3"]  # no price -> last

    desc = _provider_with_fixture(payload).search("монітор", sort="price_desc").offers
    assert [o.id for o in desc] == ["1", "4", "2", "3"]


def test_network_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).search("ssd").offers


def test_promoted_offers_excluded_by_default() -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "title": "Проплаченный SSD",
                "url": "https://example.com/1",
                "params": [
                    {"key": "price", "value": {"value": 29000, "currency": "UAH"}}
                ],
                "location": {"city": {"name": "Суми"}},
                "promotion": {"highlighted": False, "urgent": False, "top_ad": True},
            },
            {
                "id": "2",
                "title": "Обычный SSD",
                "url": "https://example.com/2",
                "params": [
                    {"key": "price", "value": {"value": 540, "currency": "UAH"}}
                ],
                "location": {"city": {"name": "Київ"}},
                "promotion": {"highlighted": False, "urgent": False, "top_ad": False},
            },
        ]
    }

    offers = _provider_with_fixture(payload).search("ssd").offers
    assert [o.id for o in offers] == ["2"]

    offers_all = _provider_with_fixture(payload).search("ssd", include_promoted=True).offers
    assert [o.id for o in offers_all] == ["1", "2"]


def test_highlighted_and_urgent_also_count_as_promoted() -> None:
    payload = {
        "data": [
            {
                "id": "1",
                "title": "VIP",
                "url": "https://example.com/1",
                "params": [
                    {"key": "price", "value": {"value": 100, "currency": "UAH"}}
                ],
                "location": {"city": {"name": "Київ"}},
                "promotion": {"highlighted": True, "urgent": False, "top_ad": False},
            },
            {
                "id": "2",
                "title": "Срочно",
                "url": "https://example.com/2",
                "params": [
                    {"key": "price", "value": {"value": 200, "currency": "UAH"}}
                ],
                "location": {"city": {"name": "Київ"}},
                "promotion": {"highlighted": False, "urgent": True, "top_ad": False},
            },
            {
                "id": "3",
                "title": "Обычный",
                "url": "https://example.com/3",
                "params": [
                    {"key": "price", "value": {"value": 300, "currency": "UAH"}}
                ],
                "location": {"city": {"name": "Київ"}},
            },
        ]
    }

    offers = _provider_with_fixture(payload).search("ssd").offers
    assert [o.id for o in offers] == ["3"]


def test_parses_real_olx_sample() -> None:
    """The parser must match a real, captured OLX API response."""
    payload = json.loads((FIXTURES_DIR / "olx_sample.json").read_text())
    result = _provider_with_fixture(payload).search("ssd")
    assert result.total == 47581

    offers = result.offers
    assert len(offers) == 1
    offer = offers[0]
    assert offer.id == "931716651"
    assert offer.title.startswith("RTX 5090 SSD")
    assert offer.price == 29000.0
    assert offer.currency == "UAH"
    assert offer.location == "Суми"
    assert offer.url.startswith("https://www.olx.ua/d/uk/obyavlenie/")


def test_parses_real_offer_details() -> None:
    """get_details must parse a real, captured OLX offer-details response."""
    payload = json.loads((FIXTURES_DIR / "olx_offer_details.json").read_text())
    details = _provider_with_fixture(payload).get_details("929558300")

    assert details.id == "929558300"
    assert details.title.startswith("SSD Диск")
    assert details.price == 540.0
    assert details.currency == "UAH"
    assert details.location == "Берестин"
    assert details.seller == "Юлія"
    assert details.status == "active"
    assert details.category_id == 3784
    # Description is stripped of HTML and readable.
    assert "TeamGroup GX1 240GB" in details.description
    assert "<br" not in details.description
    # Price is a top-level field, not duplicated in params.
    assert all(p["key"] != "price" for p in details.params)
    # Enum param keeps its human-readable label.
    assert any(p["key"] == "state" and p["value"] == "Вживане" for p in details.params)
    # Photo link template is resolved to a concrete size.
    assert details.photos and all("{width}" not in p for p in details.photos)
    assert details.photos[0].endswith("image;s=800x800")


def test_offer_details_404_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).get_details("929558300")


def test_offer_details_missing_data_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "gone"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OLXError):
        OLXProvider(client=client).get_details("929558300")
