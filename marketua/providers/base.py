"""Common provider interface.

Every marketplace (OLX, Hotline, Prom, Rozetka) is implemented behind this
one abstraction, so adding a platform never touches the MCP layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from marketua.models import SearchResult


class MarketplaceProvider(ABC):
    """Search a single marketplace and return normalised :class:`Offer` objects."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResult:
        """Return a page of offers matching ``query`` plus the total match count."""
        raise NotImplementedError
