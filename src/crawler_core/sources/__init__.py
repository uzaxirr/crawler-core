"""Auto-import every crawler module, then run any site-level discovery.

Two-phase load:

  1. Walk the package tree and import every non-underscore .py file. Each
     hand-written crawler registers itself via `@register` on import.

  2. Iterate the registry, dedupe by `discover_and_register` implementation,
     and call each unique one exactly once. Site-level intermediate bases
     (e.g. `FiSeListingCrawler`) use this to fetch a site's umbrella page
     and dynamically register a subclass for every uncovered listing.

Discovery failures are logged as warnings but never break the CLI — the
hand-written crawlers still work if a site's umbrella is unreachable.
"""

from __future__ import annotations

import importlib
import pkgutil
import warnings


# ---- Phase 1 — auto-import ---------------------------------------------

for _finder, _name, _ispkg in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
    if _ispkg:
        continue
    if _name.rsplit(".", 1)[-1].startswith("_"):
        continue
    importlib.import_module(_name)


# ---- Phase 2 — site-level discovery ------------------------------------

from crawler_core.base import Crawler, _REGISTRY  # noqa: E402 — deliberate import order

_base_impl = Crawler.discover_and_register.__func__
_seen_impls: set = {_base_impl}

DISCOVERY_REPORT: dict[str, list[str]] = {}
"""Class name → list of source_ids the class newly auto-registered."""


for _sid, _cls in list(_REGISTRY.items()):
    _impl = _cls.discover_and_register.__func__
    if _impl in _seen_impls:
        continue
    _seen_impls.add(_impl)
    try:
        _new_ids = _cls.discover_and_register()
        DISCOVERY_REPORT[_cls.__name__] = _new_ids
    except Exception as e:  # noqa: BLE001 — never let discovery break module load
        warnings.warn(
            f"discover_and_register failed on {_cls.__name__}: "
            f"{type(e).__name__}: {e}",
            stacklevel=2,
        )
        DISCOVERY_REPORT[_cls.__name__] = []
