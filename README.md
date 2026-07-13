# crawler-core

A plug-and-play crawler framework. One class per site listing, registered
via `@register`, discovered automatically. Adding a crawler is: drop a file,
no PR to any config, no changes to the core.

## Design

- **Base class** — `Crawler` in `crawler_core.base`. Provides the orchestrator
  and 4 hooks (`fetch`, `discover_pages`, `parse_items`, `classify`).
- **Registry** — `@register` decorator populates a global dict at import
  time. Auto-import in `sources/__init__.py` walks the subtree so every
  file anywhere under `sources/` is loaded.
- **One class per listing** — sites with multiple listings (e.g. fi.se has
  sanctions, reports, decisions, news) get one file per listing, each with
  its own `@register` class.
- **CLI** — `crawler-core list` / `crawler-core run <source_id>` is the
  single entry point.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) — `brew install uv`

No Docker, no headless browser, no service dependencies. `uv sync` gets
you a working setup end-to-end, including Cloudflare-fronted sites like
fatf-gafi.org (handled via `curl_cffi` — see [Fetching](#fetching) below).

## Setup

```bash
git clone git@github.com:uzaxirr/crawler-core.git
cd crawler-core
uv sync
```

## Use

```bash
uv run crawler-core list                                   # show every registered crawler
uv run crawler-core run se_fi_sanctions                    # crawl one, snapshot to data/
uv run crawler-core run se_fi_sanctions -v                 # + render results table
uv run crawler-core run --all                              # crawl every registered source
uv run crawler-core describe se_fi_sanctions               # structured self-description
uv run crawler-core list --json                            # machine-readable listing
uv run crawler-core discover https://www.fi.se/sv/publicerat/   # sub-listing coverage report
```

Snapshots land at `data/<source_id>/<UTC-date>.json`.

### Discover — what's on a site vs what we cover

`crawler-core discover <umbrella-url>` fetches the page, extracts every
same-host sub-path directly beneath it, and cross-checks against every
registered crawler's `root_url`. Answers "which listings on this site
already have a crawler, and which don't?" Directly closes the "we have no
idea what we're missing" gap.

Example against fi.se's publications index:

```bash
uv run crawler-core discover https://www.fi.se/sv/publicerat/
```

Output lists every `/sv/publicerat/<section>/` sub-listing, marked
`covered` (if a registered crawler's root URL falls under it) or
`uncovered` (add a crawler class to close the gap).

## Adding a new source

Drop a file anywhere under `src/crawler_core/sources/`. Decorate the class
with `@register`. Set `source_id`, `root_url`, and implement `parse_items()`.

Minimal example:

```python
from __future__ import annotations

from typing import ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler_core.base import Crawler, register
from crawler_core.models import DocumentType, FetchResult, RawItem


@register
class MyReportsCrawler(Crawler):
    source_id: ClassVar[str] = "org_mysite_reports"
    root_url:  ClassVar[str] = "https://mysite.example.com/reports/"
    document_type: ClassVar[DocumentType] = "report"

    def parse_items(self, fetched: FetchResult) -> list[RawItem]:
        soup = BeautifulSoup(fetched.content, "lxml")
        return [
            RawItem(
                url=urljoin(fetched.url, a["href"]),
                title=a.get_text(strip=True),
            )
            for a in soup.select("article h2 > a[href]")
        ]
```

That's the whole crawler. Immediately available in `crawler-core list`,
`crawler-core run org_mysite_reports`. Zero core changes.

### When to override which hook

| Hook | Default | Reason to override |
|---|---|---|
| `fetch(url)` | `http_get` (plain httpx) | Use `impersonate_get` for Cloudflare-fronted sites (curl_cffi + Chrome TLS) — see [Fetching](#fetching). Or plug in Playwright, FlareSolverr, custom API auth. |
| `discover_pages()` | Yields just `root_url` | Pagination — page numbers, cursor tokens, sitemap.xml, facet APIs |
| `classify(item)` | Wraps item with class `document_type`, no extractions | Site-specific typing, action extraction, entity extraction |

`parse_items()` is the only truly abstract method — every site's DOM/JSON
is different, and there's no useful default.

## Fetching

Two fetchers ship in `crawler_core.http`:

| Fetcher | Weight | Use for |
|---|---|---|
| `http_get(url)` | Plain httpx | Sites without bot detection (fi.se, most gov sites) |
| `impersonate_get(url)` | `curl_cffi` with Chrome TLS fingerprint | Sites behind Cloudflare — FATF, most anti-bot-protected sites |

Override `fetch()` on your crawler class to pick:

```python
from crawler_core.http import impersonate_get

class MyCloudflareSiteCrawler(Crawler):
    def fetch(self, url):
        return impersonate_get(url)
```

No Docker, no headless browser. `curl_cffi` ships as a normal pip dep.
If you eventually need JS execution (rare — most sites expose data via
JSON APIs discoverable in the browser network tab), plug in Playwright
or FlareSolverr the same way — override `fetch()`.

## Site-level auto-discovery

`Crawler.discover_and_register()` is an optional classmethod (default
no-op) that a site-level intermediate base can override. When called at
module load, it fetches the site's umbrella URL, smoke-tests each
sub-listing by parsing, and dynamically registers a subclass per
listing that isn't already covered by a hand-written crawler.

`FiSeListingCrawler` implements this — fetches `/sv/publicerat/`, walks
its sub-URLs, registers 5 auto-generated crawlers on top of the 4
hand-written ones. Hand-written crawlers with custom `classify` always
take precedence.

### Multiple crawlers per site

Sites with multiple listings get one file per listing. fi.se has an
intermediate base class (`FiSeListingCrawler` in `sources/fi_se/_base.py`)
that owns the shared DOM parsing and `?page=N` pagination, so each concrete
listing crawler is 3–4 lines of config:

```python
@register
class FiDecisionsCrawler(FiSeListingCrawler):
    source_id     = "se_fi_decisions"
    root_url      = "https://www.fi.se/sv/publicerat/sarskilda-pm-beslut/"
    document_type = "decision"
```

Current coverage:

```
src/crawler_core/sources/
├── fi_se/                    Swedish financial regulator (13 registered)
│   ├── _base.py              Shared DOM parser + ?page=N pagination + site discovery
│   ├── sanctions.py          + custom classify (regex entity extraction)
│   ├── decisions.py
│   ├── news.py
│   └── remissvar.py
│       (+ 5 auto-discovered by _base.py's discover_and_register)
│
└── fatf_gafi/                Financial Action Task Force (4 registered)
    ├── _base.py              JSON facet API + curl_cffi (Cloudflare bypass)
    ├── guidance.py
    ├── reports.py
    ├── recommendations.py
    └── risk_based.py
```

Each is independent — one breaking doesn't affect the others. Two very
different fetching and discovery mechanisms coexist:

- **fi.se** — httpx + DOM parsing + `?page=N` pagination + auto-discovery
- **FATF** — curl_cffi + JSON facet API + `offset=N` pagination

Both produce identical `CrawlResult` output shapes.

## Layout

```
src/crawler_core/
├── base.py       Crawler ABC + @register + registry + orchestrator + discover_and_register
├── models.py     FetchResult, RawItem, Record, Provenance, CrawlResult, ReviewFlag
├── http.py       Two fetchers: http_get (httpx) + impersonate_get (curl_cffi)
├── cli.py        Typer: list, run [--all], describe, discover
└── sources/      One file per crawler, auto-imported recursively
    ├── fi_se/           Swedish financial regulator
    │   ├── _base.py     FiSeListingCrawler (shared parser + auto-discovery)
    │   ├── sanctions.py, decisions.py, news.py, remissvar.py
    │   └── (auto-discovered listings register at import time)
    └── fatf_gafi/       Financial Action Task Force
        ├── _base.py     FatfListingCrawler (facet API + curl_cffi fetcher)
        └── guidance.py, reports.py, recommendations.py, risk_based.py
```

## What this is not (yet)

- **No health / scorecard / baseline verdicts.** Follow-up — the piece that
  makes a snapshot "trustworthy" rather than just "produced".
- **No import-time cache.** Every CLI invocation pays for site-level
  auto-discovery HTTP calls (~10–15s for fi.se). A 24h TTL cache would fix
  this trivially — deferred until it hurts enough to prioritize.
- **No persistence beyond JSON snapshots.** Everything writes to
  `data/<source>/<date>.json`. Downstream storage lands when the framework
  graduates into a larger system.
