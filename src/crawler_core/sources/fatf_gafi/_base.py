"""Shared base for FATF listing crawlers.

Discovery mechanism: the FATF publications facet API returns paginated
JSON via
  /content/fatf-gafi/en/publications/jcr:content/root/
      container_1967587261/faceted_search/results.facets.json
      ?offset=<N>&facet=<tag>

Each entry has:
  path             — /content/fatf-gafi/en/publications/<Category>/<slug>
  title            — human-readable title
  publicationDate  — ms epoch (nullable)
  description      — brief blurb

The intermediate base handles:
  * Cloudflare bypass via impersonate_get (curl_cffi + Chrome TLS)
  * Offset-based pagination through discover_pages()
  * JSON → RawItem via parse_items()

Concrete subclasses (guidance.py, reports.py, ...) set:
  * source_id, root_url, document_type
  * facet — the FATF filter tag (e.g. "fatf-gafi-faft-doc types:tag-Guidance")

This file is `_base.py` (underscore prefix) so the auto-import loop in
`sources/__init__.py` skips it — it isn't a concrete crawler itself.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import ClassVar, Iterator
from urllib.parse import quote

from crawler_core.base import Crawler
from crawler_core.http import impersonate_get
from crawler_core.models import FetchResult, RawItem


_BASE_HOST = "https://www.fatf-gafi.org"
_API_ENDPOINT = (
    f"{_BASE_HOST}/content/fatf-gafi/en/publications/jcr:content/"
    "root/container_1967587261/faceted_search/results.facets.json"
)


class FatfListingCrawler(Crawler):
    """Facet-driven FATF publications crawler.

    Subclass must set `facet`. See `guidance.py` for an example.
    """

    language: ClassVar[str] = "en"

    # Concrete subclasses set this. Empty string = no facet (all publications).
    facet: ClassVar[str] = ""

    # Offset pagination — API returns 10 items per page. Ceiling stops
    # runaway loops; the orchestrator's zero-new-URLs termination normally
    # fires long before this ceiling.
    max_offset: ClassVar[int] = 500
    offset_step: ClassVar[int] = 10

    # ---- Cloudflare bypass -----------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        """Uses curl_cffi to imitate Chrome's TLS handshake — required for
        FATF's Cloudflare-fronted endpoints. Plain httpx returns 403."""
        return impersonate_get(url)

    # ---- Discovery: offset-paginated facet API --------------------------

    def discover_pages(self) -> Iterator[tuple[str, str]]:
        facet_encoded = quote(self.facet, safe=":=") if self.facet else ""
        for offset in range(0, self.max_offset + 1, self.offset_step):
            params = f"offset={offset}"
            if facet_encoded:
                params += f"&facet={facet_encoded}"
            yield f"offset-{offset}", f"{_API_ENDPOINT}?{params}"

    # ---- Parse: JSON -> RawItem -----------------------------------------

    def parse_items(self, fetched: FetchResult) -> list[RawItem]:
        try:
            data = json.loads(fetched.content)
        except json.JSONDecodeError:
            return []

        items: list[RawItem] = []
        for result in data.get("results", []):
            path = result.get("path", "")
            if not path:
                continue

            # `path` is a JCR path — the browser-viewable URL adds .html
            item_url = f"{_BASE_HOST}{path}.html"

            published_at = None
            ms_epoch = result.get("publicationDate")
            if isinstance(ms_epoch, (int, float)) and ms_epoch > 0:
                try:
                    published_at = (
                        datetime.fromtimestamp(ms_epoch / 1000, tz=timezone.utc).date()
                    )
                except (ValueError, OSError):
                    published_at = None

            items.append(
                RawItem(
                    url=item_url,
                    title=result.get("title", "") or "",
                    published_at=published_at,
                    brief=result.get("description"),
                )
            )

        return items
