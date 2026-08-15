"""marketua MCP server.

Exposes marketplace search as MCP tools over stdio, so any MCP client
(Hermes, Claude Code, Codex, Cline, ...) can query Ukrainian marketplaces
from a plain-language prompt.

Run locally::

    python3 server.py

Or connect it as an MCP server (see README for client config).
Marketplaces can be toggled via ``.env`` (see ``.env.example``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from marketua.config import provider_enabled
from marketua.providers import HotlineProvider, OLXProvider, PromProvider
from marketua.reference import OLX_CATEGORIES, OLX_MAJOR_CITIES, OLX_REGIONS

mcp = MCPServer(
    "marketua",
    instructions=(
        "Search Ukrainian marketplaces and report structured results. Rules:\n"
        "- Never invent filter keys, region/city/category ids or prices: take them only from "
        "list_filters()/list_regions()/list_categories() results or the user's request.\n"
        "- filters values: enum/choice keys as plain strings ({'resolution': 'full_hd'}), numeric "
        "ranges as plain two-number lists ({'screen_size': [24, 24]}); {'item': [from, to]} is "
        "also accepted for ranges.\n"
        "- If a search result has a category_warning (the static OLX category snapshot is stale) "
        "or offers' categories don't match the requested one, tell the user and retry without "
        "category_id (keyword + filters work fine).\n"
        "- In your summary, mention only the filters/parameters you actually passed to "
        "search_offers (price, state, capacity, ...). Do not attribute characteristics "
        "(screen diagonal, resolution, brand, form factor) that were not part of the search.\n"
        "- Present offers as a list with title, price, currency, location and url; if "
        "total > returned, note the total number of matches.\n"
        "- Marketplaces: search_offers (OLX) returns individual listings (often used, with "
        "location); hotline_search_offers (Hotline) and prom_search_offers (Prom) return "
        "new products from shops. Pick by the user's intent: used or individual items -> "
        "OLX; price comparison of a new product across shops -> Hotline / Prom; 'best price "
        "anywhere' or a comparison -> query the relevant marketplaces and compare in your "
        "answer.\n"
        "- Rozetka: this server has no Rozetka tool; use the brightdata MCP server's browser "
        "tools instead. Navigate to https://rozetka.com.ua/ua/search/?text=<query> (never "
        "bt.rozetka.com.ua — Bright Data blocks that subdomain via robots.txt on the free "
        "tier), then snapshot; prefer wait_for_ref + snapshot over an immediate get_text, "
        "which can fail with 'Execution context was destroyed' while the SPA re-renders. "
        "When comparing prices of a new product or answering 'where to buy / cheapest', "
        "check Rozetka by default together with Hotline and Prom ('best price anywhere' = "
        "all four marketplaces). If the brightdata MCP server is not connected (no "
        "brightdata_* tools available), say so and report results from the available "
        "marketplaces only.\n"
    ),
)

# --- providers (only instantiate what is enabled via .env) ---------------

olx = OLXProvider() if provider_enabled("olx") else None
hotline = HotlineProvider() if provider_enabled("hotline") else None
prom = PromProvider() if provider_enabled("prom") else None


# --- OLX tools -----------------------------------------------------------

if olx is not None:

    @mcp.tool(
        description=(
            "Search OLX.ua (Ukrainian classified ads) and return a page of matching offers "
            "plus the total count. Returns {'total', 'returned', 'offers'}; each offer has "
            "id, title, price (UAH), currency, location, url. "
            "For category-specific attributes (brand, resolution, capacity, ...) call "
            "list_filters(query) FIRST, then pass the keys via `filters`. "
            "For region/city ids call list_regions(); for a category id call list_categories(). "
            "For comparing prices of a new product across shops, also call hotline_search_offers "
            "and prom_search_offers. For Rozetka, use the brightdata MCP server's browser tools."
        ),
    )
    def search_offers(
        query: Annotated[
            str,
            Field(
                description=(
                    "Search keywords. Put attributes that have no dedicated filter "
                    "(form-factor, brand, size) here as plain words, e.g. 'ssd 240gb 2.5' or 'диван б/у'."
                ),
            ),
        ],
        min_price: Annotated[
            float | None,
            Field(description="Minimum price in UAH (inclusive). Omit for no lower bound."),
        ] = None,
        max_price: Annotated[
            float | None,
            Field(description="Maximum price in UAH (inclusive). Omit for no upper bound."),
        ] = None,
        region_id: Annotated[
            int | None,
            Field(description="OLX region (oblast) id from list_regions(). Omit to search all of Ukraine."),
        ] = None,
        city_id: Annotated[
            int | None,
            Field(description="OLX city id from list_regions(). Omit to search the whole region/country."),
        ] = None,
        category_id: Annotated[
            int | None,
            Field(description="OLX category id from list_categories(). Narrows to one category. Omit for keyword search."),
        ] = None,
        state: Annotated[
            Literal["used", "new"] | None,
            Field(description="Condition filter: 'used' (б/у / вживане) or 'new' (нове). Omit to include both."),
        ] = None,
        filters: Annotated[
            dict[str, str | list[float] | dict] | None,
            Field(
                description=(
                    "Category-specific filters; keys and values come from list_filters(query). "
                    "Values are either a plain string (the option's key, e.g. {'resolution': 'full_hd'}) "
                    "or a plain two-number list [from, to] for ranges (e.g. {'screen_size': [24, 24]}). "
                    "The server also accepts the OLX-style {'item': [from, to]} wrapper for ranges. "
                    "Omit keys you don't need."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Maximum number of offers to return (1..50, default 20)."),
        ] = 20,
        offset: Annotated[
            int,
            Field(description="Pagination: skip the first N matches (default 0). Prefer narrowing with filters over deep pagination."),
        ] = 0,
        include_promoted: Annotated[
            bool,
            Field(description="Include paid/promoted listings (top_ad, highlighted, urgent). Default False (excluded)."),
        ] = False,
        sort: Annotated[
            Literal["newest", "price_asc", "price_desc"] | None,
            Field(
                description=(
                    "Result ordering: 'newest' = by creation date, newest first (server-side, OLX "
                    "supports it); 'price_asc' / 'price_desc' = cheapest / most expensive first "
                    "(sorts the returned page client-side — OLX ignores server-side price sort). "
                    "Omit for OLX default relevance order."
                ),
            ),
        ] = None,
    ) -> dict:
        """Return one page of offers plus the total number of matches.

        Returns {"total": total_matches, "returned": len(offers), "offers": [...]}.
        If total is much larger than returned, narrow the search with filters
        (price, region, category, state, ...) instead of paginating deeply.
        """
        result = olx.search(
            query,
            min_price=min_price,
            max_price=max_price,
            region_id=region_id,
            city_id=city_id,
            category_id=category_id,
            state=state,
            filters=filters,
            limit=limit,
            offset=offset,
            include_promoted=include_promoted,
            sort=sort,
        )
        return result.to_dict()

    @mcp.tool(
        description=(
            "Get full details for one OLX offer by id: plain-text description, "
            "characteristics, photo URLs, seller, status and dates."
        ),
    )
    def get_offer_details(
        offer_id: Annotated[
            str,
            Field(description="OLX offer id — the 'id' field of a search_offers result, e.g. '929558300'."),
        ],
    ) -> dict:
        """Return one listing's full details.

        Returns id, title, url, price, currency, location, plain-text description,
        seller name, status, created_time, category_id, characteristics (params)
        and photo URLs.
        """
        return olx.get_details(offer_id).to_dict()

    @mcp.tool(
        description=(
            "Discover which category-specific filter attributes (and sample values) exist for a "
            "search query. Call this BEFORE search_offers when the user mentions an attribute "
            "like resolution, capacity, brand, etc., so you can pass valid keys in `filters`. "
            "If the query could match several categories (e.g. 'ssd' also hits laptops), pass "
            "category_id from list_categories() to sample only that category."
        ),
    )
    def list_filters(
        query: Annotated[str, Field(description="Search phrase to inspect, e.g. 'монітор' or 'ssd'.")],
        limit: Annotated[
            int,
            Field(description="How many offers to sample (1..50, default 40)."),
        ] = 40,
        category_id: Annotated[
            int | None,
            Field(description="OLX category id from list_categories() to restrict the sample to one category. Omit for keyword-wide discovery."),
        ] = None,
    ) -> list[dict]:
        """Sample results for ``query`` and return category-specific filter attributes.

        Each entry has key, name, kind ("enum" or "range") and sample values.
        Pass enum values as {'key': 'value'} and ranges as {'key': [from, to]}
        to search_offers' ``filters`` argument. Use ``category_id`` to avoid
        cross-category noise on broad queries.
        """
        return olx.discover_filters(query, limit=limit, category_id=category_id)


# --- Hotline tool --------------------------------------------------------

if hotline is not None:

    @mcp.tool(
        description=(
            "Search Hotline.ua (Ukrainian price aggregator) and return matching product models "
            "with their price range across shops. Returns {'total', 'returned', 'offers'}; each "
            "offer has id, title, price (minimum shop price, UAH), currency, url. NOTE: Hotline "
            "returns product MODELS, not individual listings — price is a range, and location is "
            "not available in search results. Use for comparing prices/specs of a product model. "
            "For used/individual listings (with location), also call search_offers (OLX)."
        ),
    )
    def hotline_search_offers(
        query: Annotated[
            str,
            Field(description="Search keywords, e.g. 'ssd 2.5 sata' or 'монітор 24'."),
        ],
        min_price: Annotated[
            float | None,
            Field(description="Minimum product price in UAH (applied to the min shop price). Omit for no lower bound."),
        ] = None,
        max_price: Annotated[
            float | None,
            Field(description="Maximum product price in UAH (applied to the min shop price). Omit for no upper bound."),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Maximum number of products to return (default 20)."),
        ] = 20,
        offset: Annotated[
            int,
            Field(description="Pagination: skip the first N matches (default 0)."),
        ] = 0,
    ) -> dict:
        """Return one page of Hotline product models plus the total count."""
        result = hotline.search(
            query,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )
        return result.to_dict()


# --- Prom tool -----------------------------------------------------------

if prom is not None:

    @mcp.tool(
        description=(
            "Search Prom.ua (Ukrainian B2C marketplace) and return matching products. Returns "
            "'total', 'returned', 'offers'}; each offer has id, title, price (UAH), currency, "
            "url. Prom sells new products from shops (like Hotline). "
            "For used/individual listings use search_offers (OLX)."
        ),
    )
    def prom_search_offers(
        query: Annotated[
            str,
            Field(description="Search keywords, e.g. 'ssd 2.5' or 'холодильник'."),
        ],
        min_price: Annotated[
            float | None,
            Field(description="Minimum product price in UAH. Omit for no lower bound."),
        ] = None,
        max_price: Annotated[
            float | None,
            Field(description="Maximum product price in UAH. Omit for no upper bound."),
        ] = None,
        limit: Annotated[
            int,
            Field(description="Maximum number of products to return (default 20)."),
        ] = 20,
        offset: Annotated[
            int,
            Field(description="Pagination: skip the first N matches (default 0)."),
        ] = 0,
    ) -> dict:
        """Return one page of Prom products plus the total count."""
        result = prom.search(
            query,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )
        return result.to_dict()


# --- static reference tools (always available) ---------------------------

@mcp.tool(
    description=(
        "List OLX categories (id + name) so you can look up a category_id to pass to "
        "search_offers. Static snapshot of the most useful categories — the live OLX "
        "category endpoint is deprecated. Omit category_id in search_offers when the "
        "category is not listed here."
    ),
)
def list_categories() -> dict:
    """Return a curated OLX category list (static snapshot).

    Returns {"categories": [{id, name}], "note"}. Not exhaustive — use keyword
    search + filters when the category is missing.
    """
    return {
        "categories": [{"id": cid, "name": name} for cid, name in OLX_CATEGORIES.items()],
        "note": (
            "Статичний знімок: OLX задепрекейтив живий ендпоінт категорій (2026-08). "
            "Якщо потрібної категорії немає — шукай без category_id (query + filters). "
            "Id може застаріти: якщо search_offers повернув category_warning — бери свіжий "
            "id або шукай без category_id."
        ),
    }


@mcp.tool(
    description="List OLX regions (oblasts) and major cities with their ids, for search_offers region_id/city_id.",
)
def list_regions() -> dict:
    """Return OLX region_id/city_id values to pass to search_offers.

    Returns a dict with:
      - "regions": full list of 25 regions as {id, name} (use in region_id)
      - "cities": major cities as {id, name} (use in city_id; not exhaustive)
    """
    return {
        "regions": [{"id": rid, "name": name} for rid, name in OLX_REGIONS.items()],
        "cities": [{"id": cid, "name": name} for cid, name in OLX_MAJOR_CITIES.items()],
        "note": (
            "region_id = область; city_id = місто (основні наведені, повний список не захардкоджено). "
            "Обидва необов'язкові — без них пошук по всій Україні."
        ),
    }


if __name__ == "__main__":
    mcp.run()
