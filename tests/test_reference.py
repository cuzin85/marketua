"""Tests for the static OLX reference data used by the helper tools."""

from __future__ import annotations

from marketua.reference import OLX_CATEGORIES, OLX_MAJOR_CITIES, OLX_REGIONS


def test_regions_are_complete() -> None:
    assert len(OLX_REGIONS) == 25
    assert OLX_REGIONS[1] == "Сумська область"
    assert OLX_REGIONS[16] == "АР Крим"
    assert OLX_REGIONS[25] == "Київська область"


def test_major_cities_are_present() -> None:
    assert OLX_MAJOR_CITIES[268] == "Київ"
    assert OLX_MAJOR_CITIES[176] == "Львів"
    assert OLX_MAJOR_CITIES[62] == "Одеса"
    assert OLX_MAJOR_CITIES[121] == "Дніпро"


def test_categories_snapshot_is_present() -> None:
    # The live OLX category endpoint is deprecated, so a static snapshot is used.
    assert len(OLX_CATEGORIES) >= 10
    assert OLX_CATEGORIES[78] == "Комп'ютери"
    assert OLX_CATEGORIES[83] == "Монітори"
    assert OLX_CATEGORIES[80] == "Ноутбуки"
