"""Shared base class for fi.se listing crawlers.

Every fi.se listing under /sv/publicerat/ uses the same DOM shape:
`div.list-item.extended-click-area` containers with `h2 > a`, `.date`,
`a.categoryLink`, and `p.introduction` children. Pagination is always
`?page=N` (with the known no-op behavior the orchestrator catches).

This module also implements `discover_and_register` — the site-level hook
that fetches the fi.se publications umbrella, walks every sub-listing URL,
smoke-tests each by parsing, and dynamically registers a subclass for every
listing not already covered by a hand-written crawler.

This file is `_base.py` (underscore prefix) so the auto-import loop in
`sources/__init__.py` skips it — it isn't a concrete crawler itself.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from crawler_core.base import Crawler, _REGISTRY, register
from crawler_core.http import http_get
from crawler_core.models import FetchResult, RawItem


class FiSeListingCrawler(Crawler):
    """Common behavior for every fi.se /sv/publicerat/ listing.

    Provides ?page=N pagination, the shared DOM parser, and the fi.se-wide
    `discover_and_register` implementation that auto-populates the registry
    with a crawler per undiscovered listing.

    Concrete subclasses supply identity (source_id, root_url, document_type)
    and — if the listing has structured sub-fields worth extracting — a
    `classify()` override (see sanctions.py for an example).
    """

    language: ClassVar[str] = "sv"
    max_pages: ClassVar[int] = 5
    umbrella_url: ClassVar[str] = "https://www.fi.se/sv/publicerat/"

    def discover_pages(self) -> Iterator[tuple[str, str]]:
        for page in range(1, self.max_pages + 1):
            url = self.root_url if page == 1 else f"{self.root_url}?page={page}"
            yield f"page-{page}", url

    def parse_items(self, fetched: FetchResult) -> list[RawItem]:
        soup = BeautifulSoup(fetched.content, "lxml")
        items: list[RawItem] = []

        for div in soup.select("div.list-item.extended-click-area"):
            title_link = div.select_one("h2 > a")
            if title_link is None or not title_link.get("href"):
                continue

            url = urljoin(fetched.url, title_link["href"])
            title = title_link.get_text(strip=True)

            date_el = div.select_one(".date")
            published_at = (
                _parse_iso_date(date_el.get_text(strip=True)) if date_el else None
            )

            categories = [
                a.get_text(strip=True)
                for a in div.select("a.categoryLink")
                if a.get_text(strip=True)
            ]

            brief_el = div.select_one("p.introduction")
            brief = brief_el.get_text(strip=True) if brief_el else None

            items.append(
                RawItem(
                    url=url,
                    title=title,
                    published_at=published_at,
                    source_categories=categories,
                    brief=brief,
                )
            )

        return items

    # ---- Site-level discovery ------------------------------------------

    @classmethod
    def discover_and_register(cls) -> list[str]:
        """Fetch the fi.se umbrella, smoke-test each sub-listing, register
        a subclass for every valid one that isn't already covered.

        Skips:
          * URLs already covered by a hand-written crawler (either direction:
            registered.root_url starts with discovered URL, or discovered URL
            starts with registered.root_url — a sanctions subcategory already
            registered means we don't over-cover the parent sanctions/ URL)
          * URLs whose smoke-test parse returns 0 items (probably a nested
            umbrella like /rapporter/ or a non-article page like /statistik/)
          * URLs whose fetch or parse raises (probably JS-rendered or
            requires auth)

        Returns list of source_ids that were newly registered.
        """
        try:
            fetched = http_get(cls.umbrella_url, timeout=15.0)
        except Exception:
            return []

        parent = urlparse(fetched.url)
        parent_path = (
            parent.path if parent.path.endswith("/") else parent.path + "/"
        )

        soup = BeautifulSoup(fetched.content, "lxml")

        subpaths: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            absolute = urljoin(fetched.url, href)
            parsed = urlparse(absolute)
            if parsed.netloc != parent.netloc:
                continue
            if not parsed.path.startswith(parent_path):
                continue
            if parsed.path == parent_path:
                continue
            rest = parsed.path[len(parent_path):]
            first_seg = rest.split("/", 1)[0]
            if not first_seg:
                continue
            subpaths.add(parent_path + first_seg + "/")

        registered_roots = [c.root_url for c in _REGISTRY.values() if c.root_url]
        newly_registered: list[str] = []

        for subpath in sorted(subpaths):
            listing_url = f"{parent.scheme}://{parent.netloc}{subpath}"

            # Already covered — either direction of overlap.
            already_covered = any(
                root.startswith(listing_url) or listing_url.startswith(root)
                for root in registered_roots
            )
            if already_covered:
                continue

            slug = subpath.strip("/").split("/")[-1].replace("-", "_").replace("__", "_")
            source_id_val = f"se_fi_auto_{slug}"
            if source_id_val in _REGISTRY:
                continue

            # Smoke test — fetch the listing and try parse_items
            try:
                smoke = http_get(listing_url, timeout=15.0)
            except Exception:
                continue

            # Build a candidate subclass so parse_items runs bound to an
            # instance (so `self.language` etc. resolve correctly).
            candidate = type(
                f"FiAuto_{slug}",
                (cls,),
                {
                    "source_id": source_id_val,
                    "root_url": listing_url,
                    "document_type": "other",
                    "_discovered": True,
                    "__module__": cls.__module__,
                    "__qualname__": f"FiAuto_{slug}",
                },
            )

            try:
                items = candidate().parse_items(smoke)
            except Exception:
                continue

            if not items:
                # Umbrella-of-umbrellas, video page, statistics dashboard —
                # skip so we don't register a crawler that always returns 0.
                continue

            try:
                register(candidate)
                newly_registered.append(source_id_val)
                registered_roots.append(listing_url)
            except RuntimeError:
                # Race / duplicate — skip silently.
                continue

        return newly_registered


def _parse_iso_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
