"""Auto-import every crawler module recursively so @register runs on load.

Walks the whole subtree so `sources/fi_se/sanctions.py` and
`sources/fatf_gafi/publications.py` are both discovered. Adding a source
is: drop a .py file anywhere under this package. No registration list.
"""

from __future__ import annotations

import importlib
import pkgutil


for _finder, _name, _ispkg in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
    if _ispkg:
        continue
    if _name.rsplit(".", 1)[-1].startswith("_"):
        continue
    importlib.import_module(_name)
