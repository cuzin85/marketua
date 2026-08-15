"""OLX.ua provider.

Uses the free, unauthenticated JSON API:

    GET https://www.olx.ua/api/v1/offers/?query=...&limit=...

The response is parsed defensively: the exact shape of the ``params`` /
``location`` fields has varied over time, so extraction is tolerant of
small differences. See tests for the expected structure.

Category-specific attributes (resolution, capacity, manufacturer, ...) are
handled generically: ``search`` accepts a ``filters`` dict that maps an
attribute key to either a string (enum filter) or a ``[from, to]`` pair
(range filter), and ``discover_filters`` samples results to report which
attributes exist for a given query.
"""

from __future__ import annotations

import html
import re

import httpx

from marketua.models import Offer, OfferDetails, SearchResult
from marketua.providers.base import MarketplaceProvider
from marketua.reference import OLX_CATEGORIES

OLX_OFFERS_URL = "https://www.olx.ua/api/v1/offers/"
# Note: the category tree endpoint (`/api/v1/categories`) was deprecated by OLX
# in 2026-08 — see marketua/reference.OLX_CATEGORIES for a static snapshot.

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
}

MAX_LIMIT = 50

# Default resolution substituted into OLX photo link templates.
PHOTO_SIZE = "800x800"

# Valid values for the ``state`` (condition) enum filter.
STATE_VALUES = {"used", "new"}

# Supported ``sort`` values. Only ``newest`` maps to a real OLX server-side
# parameter (``sort_by=created_at:desc``); price sorting is applied client-side
# to the returned page, because OLX ignores ``sort_by=price:*``.
SORT_VALUES = {"newest", "price_asc", "price_desc"}

# Universal filters already exposed as named tool args — skip them in
# ``discover_filters`` so the output shows only category-specific attributes.
NAMED_FILTER_KEYS = {"price", "state"}


class OLXError(RuntimeError):
    """Raised when OLX returns an unusable response."""


class OLXProvider(MarketplaceProvider):
    """Search OLX.ua and map raw API items to :class:`Offer` objects."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        # A client is injectable so tests can pass a mocked transport.
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=15.0,
            follow_redirects=True,
        )

    # --- search ----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        min_price: float | None = None,
        max_price: float | None = None,
        region_id: int | None = None,
        city_id: int | None = None,
        category_id: int | None = None,
        state: str | None = None,
        filters: dict[str, str | list[float]] | None = None,
        limit: int = 20,
        offset: int = 0,
        include_promoted: bool = False,
        sort: str | None = None,
    ) -> SearchResult:
        """Fetch offers and parse them.

        ``filters`` is a generic map for category-specific attributes:
        a string value becomes ``filter_enum_<key>=<value>``, a ``[from, to]``
        pair becomes ``filter_float_<key>:from/to``. Use ``discover_filters``
        to find valid keys for a query.

        ``state`` filters by condition and must be one of ``"used"`` / ``"new"``.
        Paid/promoted listings (``top_ad`` / ``highlighted`` / ``urgent``)
        are excluded unless ``include_promoted`` is true.

        Raises :class:`OLXError` on network failures, timeouts, HTTP errors
        or a malformed (non-JSON / missing ``data``) response.
        """
        params: dict[str, object] = {
            "query": query,
            "offset": offset,
            "limit": max(1, min(int(limit), MAX_LIMIT)),
        }
        # OLX's actual API params differ from the friendly names we expose.
        if min_price is not None:
            params["filter_float_price:from"] = min_price
        if max_price is not None:
            params["filter_float_price:to"] = max_price
        if region_id is not None:
            params["region_id"] = region_id
        if city_id is not None:
            params["city_id"] = city_id
        if category_id is not None:
            params["category_id"] = category_id
        if state is not None:
            if state not in STATE_VALUES:
                raise OLXError(
                    f"Invalid state {state!r}; expected one of {sorted(STATE_VALUES)}"
                )
            params["filter_enum_state"] = state
        if sort is not None:
            if sort not in SORT_VALUES:
                raise OLXError(
                    f"Invalid sort {sort!r}; expected one of {sorted(SORT_VALUES)}"
                )
            # Only ``newest`` has a real server-side counterpart on OLX.
            if sort == "newest":
                params["sort_by"] = "created_at:desc"
        self._apply_generic_filters(params, filters)

        items, total = self._request(params)

        if not include_promoted:
            items = [i for i in items if not self._is_promoted(i)]

        offers = [self._parse_item(item) for item in items]
        if sort == "price_asc":
            offers.sort(key=lambda o: (o.price is None, o.price if o.price is not None else 0.0))
        elif sort == "price_desc":
            offers.sort(key=lambda o: (o.price is None, -(o.price if o.price is not None else 0.0)))

        result = SearchResult(offers=offers, total=total)
        self._guard_category(result, category_id)
        return result

    # --- offer details ---------------------------------------------------

    def get_details(self, offer_id: str | int) -> OfferDetails:
        """Fetch and parse a single offer's full details by its OLX id."""
        url = f"{OLX_OFFERS_URL}{offer_id}/"
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OLXError(f"OLX offer details request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OLXError("OLX offer details returned non-JSON") from exc

        item = payload.get("data")
        if not isinstance(item, dict) or not item:
            raise OLXError(
                f"OLX offer details has no 'data' object: {list(payload)[:5]}"
            )
        return self._parse_details(item)

    @staticmethod
    def _apply_generic_filters(
        params: dict[str, object], filters: dict[str, object] | None
    ) -> None:
        for key, value in (filters or {}).items():
            # Tolerate models that wrap a range in OLX-style {"item": [from, to]}.
            if isinstance(value, dict):
                item = value.get("item")
                if isinstance(item, (list, tuple)):
                    value = item
            if isinstance(value, (list, tuple)):
                low = value[0] if len(value) > 0 else None
                high = value[1] if len(value) > 1 else None
                if low is not None:
                    params[f"filter_float_{key}:from"] = low
                if high is not None:
                    params[f"filter_float_{key}:to"] = high
            else:
                params[f"filter_enum_{key}"] = value

    # --- filter discovery ------------------------------------------------

    def discover_filters(
        self,
        query: str,
        limit: int = 40,
        category_id: int | None = None,
    ) -> list[dict]:
        """Sample results for ``query`` and report available attribute filters.

        Pass ``category_id`` (from ``list_categories``) to sample results from a
        single category — broad queries otherwise mix several categories and
        produce noisy filter attributes (e.g. ``ssd`` also returns laptops).
        """
        params: dict[str, object] = {
            "query": query,
            "offset": 0,
            "limit": max(1, min(int(limit), MAX_LIMIT)),
        }
        if category_id is not None:
            params["category_id"] = category_id
        items, _ = self._request(params)
        return self._aggregate_filters(items)

    @staticmethod
    def _aggregate_filters(items: list[dict]) -> list[dict]:
        by_key: dict[str, dict] = {}
        for item in items:
            for param in item.get("params", []) or []:
                if not isinstance(param, dict):
                    continue
                key = param.get("key")
                if not key or key in NAMED_FILTER_KEYS:
                    continue
                entry = by_key.setdefault(
                    key,
                    {
                        "key": key,
                        "name": param.get("name"),
                        "type": param.get("type"),
                        "kind": "range" if param.get("type") == "input" else "enum",
                        "values": {},
                    },
                )
                value = param.get("value")
                if isinstance(value, dict) and value.get("key") is not None:
                    entry["values"][str(value["key"])] = value.get("label")

        result = []
        for key in sorted(by_key):
            entry = by_key[key]
            values = [
                {"key": k, "label": v}
                for k, v in sorted(entry["values"].items(), key=lambda kv: str(kv[1]))
            ]
            result.append(
                {
                    "key": entry["key"],
                    "name": entry["name"],
                    "type": entry["type"],
                    "kind": entry["kind"],
                    "values": values,
                }
            )
        return result

    # --- HTTP ------------------------------------------------------------

    def _request(self, params: dict[str, object]) -> tuple[list[dict], int | None]:
        """GET the offers endpoint and return (data items, visible_total_count)."""
        try:
            response = self._client.get(OLX_OFFERS_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            hint = ""
            status = getattr(exc, "response", None)
            if (
                status is not None
                and status.status_code == 400
                and "category_id" in params
            ):
                hint = (
                    " OLX rejected the request (400) — the category_id is likely stale; "
                    "retry without category_id or with a fresh id from list_categories()."
                )
            raise OLXError(f"OLX request failed: {exc}.{hint}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OLXError("OLX returned a non-JSON response") from exc

        items = payload.get("data")
        if not isinstance(items, list):
            raise OLXError(
                f"OLX response has no 'data' list: {list(payload)[:5]}"
            )

        total = None
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and metadata.get("visible_total_count") is not None:
            total = int(metadata["visible_total_count"])
        return items, total

    # --- parsing ---------------------------------------------------------

    @staticmethod
    def _is_promoted(item: dict) -> bool:
        """True if the listing is a paid placement, not an organic result."""
        promotion = item.get("promotion")
        if not isinstance(promotion, dict):
            return False
        return bool(
            promotion.get("top_ad")
            or promotion.get("highlighted")
            or promotion.get("urgent")
        )

    @staticmethod
    def _parse_item(item: dict) -> Offer:
        category = item.get("category")
        category_id = None
        if isinstance(category, dict) and category.get("id") is not None:
            category_id = int(category["id"])
        return Offer(
            id=str(item.get("id", "")),
            title=item.get("title") or "",
            url=item.get("url") or "",
            price=OLXProvider._extract_price(item),
            currency=OLXProvider._extract_currency(item),
            location=OLXProvider._extract_location(item),
            category_id=category_id,
            category_name=OLX_CATEGORIES.get(category_id) if category_id is not None else None,
        )

    @staticmethod
    def _guard_category(result: SearchResult, category_id: int | None) -> None:
        """Detect a stale ``category_id`` from the static snapshot at query time.

        If OLX ignores a dead/renumbered id, the returned offers carry different
        ``category.id`` values than requested — that is positive evidence of
        staleness (an empty result is ambiguous, so it is not flagged).
        """
        if category_id is None or not result.offers:
            return
        result.searched_category = {
            "id": category_id,
            "name": OLX_CATEGORIES.get(category_id),
        }
        seen = {o.category_id for o in result.offers if o.category_id is not None}
        if seen != {category_id}:
            others = ", ".join(sorted(str(c) for c in seen - {category_id}))
            name = OLX_CATEGORIES.get(category_id) or "unknown"
            result.category_warning = (
                f"category_id={category_id} ({name}) no longer matches what OLX returned "
                f"(offers are in categories: {others}). The id in the static snapshot is "
                "stale — retry without category_id or pick a fresh id from list_categories()."
            )

    @staticmethod
    def _find_param(item: dict, key: str) -> dict | None:
        """Find a top-level entry in ``item["params"]`` by its ``key``."""
        params = item.get("params")
        if not isinstance(params, list):
            return None
        for entry in params:
            if isinstance(entry, dict) and entry.get("key") == key:
                return entry
        return None

    @staticmethod
    def _extract_price(item: dict) -> float | None:
        entry = OLXProvider._find_param(item, "price")
        value = entry.get("value") if entry else None

        # ``value`` is usually a nested dict like {"value": "350", ...}.
        if isinstance(value, dict):
            value = value.get("value")

        if value is None:
            return None
        try:
            return float(str(value).replace("\u00a0", "").replace(" ", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_currency(item: dict) -> str | None:
        entry = OLXProvider._find_param(item, "price")
        value = entry.get("value") if entry else None
        if isinstance(value, dict):
            currency = value.get("currency")
            if isinstance(currency, str):
                return currency
        return None

    @staticmethod
    def _extract_location(item: dict) -> str | None:
        location = item.get("location")
        if not isinstance(location, dict):
            return None
        city = location.get("city")
        region = location.get("region")
        if isinstance(city, dict) and city.get("name"):
            return str(city["name"])
        if isinstance(region, dict) and region.get("name"):
            return str(region["name"])
        return None

    @classmethod
    def _parse_details(cls, item: dict) -> OfferDetails:
        params = []
        for entry in item.get("params") or []:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            # Price is already exposed as a top-level field.
            if not key or key == "price":
                continue
            params.append(
                {
                    "key": key,
                    "name": entry.get("name"),
                    "value": cls._format_param_value(entry),
                }
            )

        photos = []
        for photo in item.get("photos") or []:
            if not isinstance(photo, dict):
                continue
            link = photo.get("link")
            if isinstance(link, str):
                photos.append(link.replace("{width}x{height}", PHOTO_SIZE))

        user = item.get("user")
        seller = user.get("name") if isinstance(user, dict) else None

        category = item.get("category")
        category_id = None
        if isinstance(category, dict) and category.get("id") is not None:
            category_id = int(category["id"])

        return OfferDetails(
            id=str(item.get("id", "")),
            title=item.get("title") or "",
            url=item.get("url") or "",
            description=cls._clean_description(item.get("description")),
            price=cls._extract_price(item),
            currency=cls._extract_currency(item),
            location=cls._extract_location(item),
            seller=seller,
            status=item.get("status"),
            created_time=item.get("created_time"),
            category_id=category_id,
            params=params,
            photos=photos,
        )

    @staticmethod
    def _format_param_value(param: dict) -> object:
        """Turn a raw param into a single human-readable value."""
        value = param.get("value")
        if isinstance(value, dict):
            label = value.get("label")
            if label is not None:
                return label
            for key in ("value", "key"):
                if value.get(key) is not None:
                    return value[key]
        return value

    @staticmethod
    def _clean_description(text: str | None) -> str:
        """Strip OLX description HTML down to plain text."""
        if not text:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text).strip()
