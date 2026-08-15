"""Prom.ua provider.

Prom's public search API is seller-only, and its GraphQL has introspection
disabled, so this provider parses the SSR search page:

    GET https://prom.ua/ua/search?search_term=<query>&page=<page>

Each product card is embedded as a schema.org ``Product`` JSON-LD block
(name, url, offers.price / priceCurrency, seller). ~10 products per page;
the total match count is in an embedded JSON state (``"total": N``).

Price filtering is applied client-side after parsing (no reliable URL
price filter on the search endpoint).
"""

from __future__ import annotations

import html
import json
import re

import httpx
from bs4 import BeautifulSoup

from marketua.models import Offer, SearchResult
from marketua.providers.base import MarketplaceProvider

PROM_SEARCH_URL = "https://prom.ua/ua/search"

ITEMS_PER_PAGE = 10

PROM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk,ru;q=0.9,en;q=0.7",
}

# Matches the product id embedded in prom.ua urls, e.g. /ua/m8634975113066207435-...
_PRODUCT_ID_RE = re.compile(r"/ua/m(\d+)")


class PromError(RuntimeError):
    """Raised when Prom returns an unusable response."""


class PromProvider(MarketplaceProvider):
    """Search Prom.ua and map product JSON-LD blocks to :class:`Offer` objects."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        # A client is injectable so tests can pass a mocked transport.
        self._client = client or httpx.Client(
            headers=PROM_HEADERS,
            timeout=15.0,
            follow_redirects=True,
        )

    def search(
        self,
        query: str,
        *,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResult:
        """Fetch the SSR search page and parse JSON-LD product blocks.

        ``min_price`` / ``max_price`` are applied client-side on the parsed
        price. Raises :class:`PromError` on network failures, HTTP errors or
        an unparseable page.
        """
        params: dict[str, object] = {"search_term": query}
        if offset > 0:
            params["page"] = offset // ITEMS_PER_PAGE + 1

        try:
            response = self._client.get(PROM_SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PromError(f"Prom search request failed: {exc}") from exc

        products = self._parse_products(response.text)
        if not products:
            raise PromError("Prom search page has no product JSON-LD blocks")

        offers = [self._parse_product(p) for p in products]
        offers = [o for o in offers if o is not None]

        if min_price is not None:
            offers = [o for o in offers if o.price is not None and o.price >= min_price]
        if max_price is not None:
            offers = [o for o in offers if o.price is not None and o.price <= max_price]

        start = offset % ITEMS_PER_PAGE
        page = offers[start : start + limit]
        return SearchResult(offers=page, total=self._parse_total(response.text))

    # --- parsing ---------------------------------------------------------

    @staticmethod
    def _parse_products(page: str) -> list[dict]:
        """Return the parsed schema.org ``Product`` JSON-LD blocks."""
        soup = BeautifulSoup(page, "html.parser")
        products: list[dict] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                products.append(data)
        return products

    @classmethod
    def _parse_product(cls, product: dict) -> Offer | None:
        url = product.get("url") or ""
        if not url:
            return None
        name = product.get("name") or ""
        if isinstance(name, str):
            name = html.unescape(name)

        price: float | None = None
        currency: str | None = None
        offers = product.get("offers")
        if isinstance(offers, dict):
            price = cls._to_float(offers.get("price"))
            currency = offers.get("priceCurrency")

        m = _PRODUCT_ID_RE.search(url)
        offer_id = m.group(1) if m else url
        return Offer(
            id=offer_id,
            title=name,
            url=url,
            price=price,
            currency=currency,
            location=None,
        )

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace("\u00a0", "").replace(" ", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_total(page: str) -> int | None:
        """Parse the embedded total match count, e.g. ``"total":6513``."""
        m = re.search(r'"total"\s*:\s*(\d+)', page)
        return int(m.group(1)) if m else None
