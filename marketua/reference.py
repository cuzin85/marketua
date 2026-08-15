"""Static OLX.ua reference data for the helper tools.

Kept hardcoded (not fetched live) so ``list_regions`` / ``list_categories``
work offline and stay stable across OLX layout changes. Verified against the
live API in 2026-08 — re-check if OLX changes its location or category tree.

Category-specific filter attributes are NOT hardcoded here: they are
discovered dynamically by ``list_filters(query)`` (see OLXProvider).
"""

from __future__ import annotations

# region_id -> oblast name. There are 25 regions (24 oblasts + Crimea).
OLX_REGIONS: dict[int, str] = {
    1: "Сумська область",
    2: "Луганська область",
    3: "Херсонська область",
    4: "Донецька область",
    5: "Львівська область",
    6: "Житомирська область",
    7: "Кіровоградська область",
    8: "Харківська область",
    9: "Одеська область",
    10: "Закарпатська область",
    11: "Тернопільська область",
    12: "Черкаська область",
    13: "Івано-Франківська область",
    14: "Рівненська область",
    15: "Полтавська область",
    16: "АР Крим",
    17: "Запорізька область",
    18: "Чернівецька область",
    19: "Миколаївська область",
    20: "Хмельницька область",
    21: "Дніпропетровська область",
    22: "Волинська область",
    23: "Чернігівська область",
    24: "Вінницька область",
    25: "Київська область",
}

# OLX deprecated the live category-tree endpoint (`/api/v1/categories` returns
# "This API is deprecated" since 2026-08-14), so this is a static snapshot of the
# most useful categories. Ids were verified by sampling live search results
# (each offer carries `category.id`) and names were checked against listing
# content in 2026-08. Re-check if OLX changes its category ids. Not exhaustive:
# search_offers also works fine without category_id (keyword + filters).
# Since 2026-08-16 search() guards against stale ids at query time: it echoes
# searched_category and emits a category_warning when OLX returns offers in
# categories other than the requested id (see OLXProvider._guard_category).
OLX_CATEGORIES: dict[int, str] = {
    73: "Фотоапарати",
    75: "Телевізори",
    78: "Комп'ютери",
    80: "Ноутбуки",
    83: "Монітори",
    85: "Телефони",
    370: "Холодильники",
    386: "Пральні машини",
    458: "Комплектуючі для ПК (відеокарти, пам'ять)",
    511: "Меблі",
    523: "Меблі для кухні",
    655: "Інструменти (ручні)",
    657: "Інструменти (електро) та садова техніка",
    889: "Дитячі іграшки",
    3416: "Велосипеди",
    3711: "Квартири (оренда)",
    3784: "Комплектуючі для ноутбуків (SSD, пам'ять)",
}

# Confirmed city ids for major cities (examples — the full city tree is large).
OLX_MAJOR_CITIES: dict[int, str] = {
    268: "Київ",
    176: "Львів",
    62: "Одеса",
    194: "Запоріжжя",
    313: "Вінниця",
    145: "Черкаси",
    61: "Херсон",
    106: "Миколаїв",
    369: "Чернівці",
    362: "Тернопіль",
    69: "Кропивницький",
    47: "Суми",
    221: "Кременчук",
    121: "Дніпро",
}
