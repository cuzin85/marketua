"""Domain model shared by all marketplace providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Offer:
    """A single marketplace listing, normalised across providers."""

    id: str
    title: str
    url: str
    price: float | None = None
    currency: str | None = None
    location: str | None = None
    category_id: int | None = None
    category_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict for the MCP tool response."""
        return {
            "id": self.id,
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "url": self.url,
            "category_id": self.category_id,
            "category_name": self.category_name,
        }


@dataclass
class SearchResult:
    """A page of offers plus the total number of matching listings."""

    offers: list[Offer]
    total: int | None = None
    # OLX only: what the caller asked to filter by, and a warning when the
    # static category snapshot no longer matches what OLX actually returned.
    searched_category: dict[str, Any] | None = None
    category_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the page: total matches, how many were returned, and the offers."""
        result: dict[str, Any] = {
            "total": self.total,
            "returned": len(self.offers),
            "offers": [offer.to_dict() for offer in self.offers],
        }
        if self.searched_category is not None:
            result["searched_category"] = self.searched_category
        if self.category_warning is not None:
            result["category_warning"] = self.category_warning
        return result


@dataclass
class OfferDetails:
    """Full details of a single listing, normalised across providers."""

    id: str
    title: str
    url: str
    description: str
    price: float | None = None
    currency: str | None = None
    location: str | None = None
    seller: str | None = None
    status: str | None = None
    created_time: str | None = None
    category_id: int | None = None
    params: list[dict[str, Any]] | None = None
    photos: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise full listing details for the MCP tool response."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "description": self.description,
            "seller": self.seller,
            "status": self.status,
            "created_time": self.created_time,
            "category_id": self.category_id,
            "params": self.params or [],
            "photos": self.photos or [],
        }
