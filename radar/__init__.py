from __future__ import annotations

import importlib
import sys


_ALIASES = {
    "analyzer": "priceradar.analyzer",
    "collector": "priceradar.collector",
    "exceptions": "priceradar.exceptions",
    "models": "priceradar.models",
    "nl_query": "radar_core.nl_query",
    "reporter": "priceradar.reporter",
    "search_index": "radar_core.search_index",
    "storage": "priceradar.storage",
}


for _name, _target in _ALIASES.items():
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(_target)


__all__ = sorted(_ALIASES)
