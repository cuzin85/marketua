"""Hotline.ua provider.

Hotline is a price aggregator: a search returns product **models** (not
individual listings), each with a price range across shops. The public
GraphQL API is mostly behind a request-token anti-bot gate, so this
provider parses the SSR search page instead:

    GET https://hotline.ua/ua/sr/?q=<query>&p=<page>

~48 product cards per page; titles/prices live in the HTML. The URL
price filters (``price[min]``/``price[max]``) are ignored by the search
endpoint, so price filtering is applied client-side after parsing.

Product ids are not exposed on the cards, so the id is the URL path
(e.g. ``/ua/computer-karmany-dlya-hdd/...``) — stable across requests.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from marketua.models import Offer, SearchResult
from marketua.providers.base import MarketplaceProvider

HOTLINE_SEARCH_URL = "https://hotline.ua/ua/sr/"
HOTLINE_BASE = "https://hotline.ua"

ITEMS_PER_PAGE = 48

HOTLINE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk,ru;q=0.9,en;q=0.7",
}

CARD_SELECTOR = "div.list-item.list-item--column"

_NBSP = "\u00a0"


class HotlineError(RuntimeError):
    """Raised when Hotline returns an unusable response."""


class HotlineProvider(MarketplaceProvider):
    """Search Hotline.ua and map product-model cards to :class:`Offer` objects."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        # A client is injectable so tests can pass a mocked transport.
        self._client = client or httpx.Client(
            headers=HOTLINE_HEADERS,
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
        """Fetch the SSR search page and parse product cards into offers.

        ``price`` on an :class:`Offer` is the **minimum** shop price for the
        product model (Hotline cards show a price range). ``min_price`` /
        ``max_price`` are applied client-side because Hotline's search URL
        ignores its price filter parameters.

        Raises :class:`HotlineError` on network failures, HTTP errors or an
        unparseable page.
        """
        params: dict[str, object] = {"q": query}
        if offset > 0:
            params["p"] = offset // ITEMS_PER_PAGE + 1

        try:
            response = self._client.get(HOTLINE_SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HotlineError(f"Hotline search request failed: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(CARD_SELECTOR)
        if not cards:
            raise HotlineError("Hotline search page has no product cards")

        offers = [self._parse_card(card) for card in cards]
        offers = [o for o in offers if o is not None]

        if min_price is not None:
            offers = [o for o in offers if o.price is not None and o.price >= min_price]
        if max_price is not None:
            offers = [o for o in offers if o.price is not None and o.price <= max_price]

        start = offset % ITEMS_PER_PAGE
        page = offers[start : start + limit]
        return SearchResult(offers=page, total=self._parse_total(soup))

    # --- parsing ---------------------------------------------------------

    @classmethod
    def _parse_card(cls, card) -> Offer | None:
        """Extract title, url and min price from one product card."""
        link = card.select_one("a.item-title")
        if link is None:
            return None
        href = link.get("href") or ""
        if not href:
            return None

        price_min, _ = cls._parse_price(card)
        return Offer(
            id=href,
            title=link.get_text(" ", strip=True),
            url=f"{HOTLINE_BASE}{href}" if href.startswith("/") else href,
            price=price_min,
            currency="UAH",
            location=None,
        )

    @staticmethod
    def _parse_price(card) -> tuple[float | None, float | None]:
        """Parse the price block: ``"7 230 – 10 320 ₴"`` or ``"8 630 ₴"``.

        Returns (min, max); for a single price both are the same value.
        """
        value = card.select_one("div.list-item__value")
        if value is None:
            return None, None
        # The price value sits in the orange block inside the value container.
        price_el = value.select_one("div.text-orange") or value
        text = price_el.get_text(" ", strip=True)

        m = re.search(r"([\d\s" + _NBSP + r"]+)\s*[–—-]\s*([\d\s" + _NBSP + r"]+)\s*₴", text)
        if m:
            return HotlineProvider._to_float(m.group(1)), HotlineProvider._to_float(m.group(2))
        m = re.search(r"([\d\s" + _NBSP + r"]+)\s*₴", text)
        if m:
            price = HotlineProvider._to_float(m.group(1))
            return price, price
        return None, None

    @staticmethod
    def _to_float(text: str) -> float | None:
        try:
            return float(text.replace(_NBSP, "").replace(" ", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_total(soup) -> int | None:
        """Parse the result counter, e.g. ``"знайдено 10000+ товарів"``."""
        text = soup.get_text(" ", strip=True)
        m = re.search(r"знайдено\s+([\d\s" + _NBSP + r"]+)\s*\+?\s*товар", text, re.IGNORECASE)
        if not m:
            return None
        try:
            return int(m.group(1).replace(_NBSP, "").replace(" ", ""))
        except ValueError:
            return None
