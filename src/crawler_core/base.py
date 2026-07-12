"""Base class, registry, and orchestrator for pluggable per-site crawlers.

Contract for a subclass:

  1. Set `source_id` and `root_url` as class attributes.
  2. Implement `parse_items(fetched) -> list[RawItem]` — this is the only
     truly abstract step; every site's HTML/JSON is different.
  3. Optionally override:
       * `fetch(url)` for anti-bot, JS-rendered pages, or custom auth
       * `discover_pages()` for pagination beyond the root URL
       * `classify(item)` for site-specific document typing, actions, entity

Everything else — dedup, the crawl loop, review-queue plumbing — is the
base class's job. The orchestrator `crawl()` is NOT overridable.

Adding a new site is: drop a file under `sources/…`, decorate with
`@register`, done. No core changes, no PR to a config file.
"""

from __future__ import annotations

import re
import warnings
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Iterator

from crawler_core.http import http_get
from crawler_core.models import (
    CrawlResult,
    DocumentType,
    FetchResult,
    Provenance,
    RawItem,
    Record,
    ReviewFlag,
)


# ---- Registry ---------------------------------------------------------------

_REGISTRY: dict[str, type["Crawler"]] = {}

_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def register(cls: type["Crawler"]) -> type["Crawler"]:
    """Class decorator — makes a Crawler subclass discoverable.

    Enforces a non-empty `source_id` and rejects duplicates. Emits a warning
    (does NOT fail) if the id doesn't match the recommended snake_case
    convention `<region>_<org>_<listing>` — the convention is for grep-ability
    and consistency, not correctness.
    """
    source_id: str = getattr(cls, "source_id", "") or ""
    if not source_id:
        raise RuntimeError(f"{cls.__name__} must set a non-empty source_id")

    if source_id in _REGISTRY:
        existing = _REGISTRY[source_id].__name__
        raise RuntimeError(
            f"duplicate source_id {source_id!r} — "
            f"existing: {existing}, new: {cls.__name__}"
        )

    if not _SOURCE_ID_RE.match(source_id):
        warnings.warn(
            f"source_id {source_id!r} on {cls.__name__} does not follow the "
            f"lowercase snake_case convention (e.g. 'se_fi_sanctions'). "
            f"Registered anyway.",
            stacklevel=2,
        )

    _REGISTRY[source_id] = cls
    return cls


def get_crawler(source_id: str) -> type["Crawler"]:
    """Look up a registered crawler class by source_id."""
    if source_id not in _REGISTRY:
        raise KeyError(
            f"unknown source_id {source_id!r}. "
            f"registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[source_id]


def all_sources() -> list[str]:
    """Every registered source_id, sorted."""
    return sorted(_REGISTRY)


# ---- Base class -------------------------------------------------------------


class Crawler(ABC):
    """Base for a per-site listing crawler.

    Subclasses set `source_id`, `root_url`, and implement `parse_items`.
    The default classify() is a minimal wrapper — override for site-specific
    document typing, action extraction, and entity extraction.
    """

    # Set by subclass -----------------------------------------------------
    source_id: ClassVar[str] = ""
    root_url: ClassVar[str] = ""
    language: ClassVar[str] = "en"
    document_type: ClassVar[DocumentType] = "other"

    # Set to True on dynamically-generated subclasses from discover_and_register
    _discovered: ClassVar[bool] = False

    # ---- Layer 1 — Discovery -------------------------------------------

    def discover_pages(self) -> Iterator[tuple[str, str]]:
        """Yield `(page_label, url)` for every listing page to fetch.

        Default: just the root URL. Override for pagination — page numbers,
        cursor tokens, sitemap.xml, facet APIs, etc.
        """
        yield "root", self.root_url

    # ---- Layer 2 — Fetch -----------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL. Default: plain HTTP GET.

        Override for FlareSolverr (Cloudflare bypass), Playwright (JS
        rendering), or API clients with auth.
        """
        return http_get(url)

    # ---- Layer 3 — Parse -----------------------------------------------

    @abstractmethod
    def parse_items(self, fetched: FetchResult) -> list[RawItem]:
        """Turn a fetched page into a list of RawItems.

        The only truly abstract method — every site's DOM/JSON is different.
        Use `fetched.url` as the base URL when resolving relative hrefs.
        """
        ...

    # ---- Layer 4 — Classify --------------------------------------------

    def classify(self, item: RawItem) -> tuple[Record, list[str]]:
        """Turn a RawItem into a Record + optional review warnings.

        Default: wrap the item, apply the class-level `document_type`, no
        actions or entity extracted. Override for site-specific extraction.
        """
        record = Record(
            url=item.url,
            title=item.title,
            published_at=item.published_at,
            source_categories=item.source_categories,
            brief=item.brief,
            language=self.language,
            document_type=self.document_type,
            actions=[],
            entity=None,
            provenance=Provenance(
                document_type_rule=f"class_default:{self.document_type}",
                actions_rules=[],
                entity_rule=None,
            ),
        )
        return record, []

    # ---- Site-level discovery (optional) -------------------------------

    @classmethod
    def discover_and_register(cls) -> list[str]:
        """Optionally discover sub-listings from a site umbrella and register
        one subclass per listing.

        Called once per unique implementation during module load, after every
        source file has been auto-imported. Default: no-op — returns `[]`.

        Override in a site-level intermediate base (e.g. `FiSeListingCrawler`)
        to fetch a site's umbrella URL, extract every sub-listing URL, smoke
        test each by attempting to parse, and dynamically build + `@register`
        a subclass per validated listing. Already-covered URLs should be
        skipped so hand-written crawlers with custom `classify()` take
        precedence over auto-discovered ones.

        Set `_discovered = True` on every dynamically-created subclass so
        `describe()` can report whether a crawler was hand-written or found.

        Returns:
            List of source_ids that this call newly registered.
        """
        return []

    # ---- Introspection --------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Structured self-description — powers `list --json` and future tooling."""
        overridden = [
            name
            for name in ("fetch", "discover_pages", "classify")
            if getattr(type(self), name) is not getattr(Crawler, name)
        ]
        return {
            "source_id": self.source_id,
            "class_name": type(self).__name__,
            "root_url": self.root_url,
            "language": self.language,
            "document_type": self.document_type,
            "overridden_hooks": overridden,
            "registration": "discovered" if self._discovered else "hand",
        }

    # ---- Orchestrator — do not override --------------------------------

    def crawl(self) -> CrawlResult:
        """Run the full crawl and return a CrawlResult.

        Loop: for each discovered page, fetch → parse → dedup → classify →
        collect. Stops early if a page adds zero new URLs (catches sites
        whose pagination silently returns page 1 forever).
        """
        started_at = datetime.now(timezone.utc)
        records: list[Record] = []
        review_queue: list[ReviewFlag] = []
        seen_urls: set[str] = set()
        pages_fetched = 0

        for _page_label, url in self.discover_pages():
            fetched = self.fetch(url)
            pages_fetched += 1
            new_this_page = 0

            for raw in self.parse_items(fetched):
                if raw.url in seen_urls:
                    continue
                seen_urls.add(raw.url)
                new_this_page += 1

                record, warnings_ = self.classify(raw)
                records.append(record)
                for reason in warnings_:
                    review_queue.append(ReviewFlag(url=raw.url, reason=reason))

            if new_this_page == 0 and pages_fetched > 1:
                break

        return CrawlResult(
            source_id=self.source_id,
            crawled_at=started_at,
            pages_fetched=pages_fetched,
            records=records,
            review_queue=review_queue,
        )
