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

## Setup

```bash
git clone <repo>
cd crawler-core
uv sync
```

## Use

```bash
uv run crawler-core list                       # show every registered crawler
uv run crawler-core run se_fi_sanctions        # crawl, snapshot to data/
uv run crawler-core run se_fi_sanctions -v     # + render results table
uv run crawler-core describe se_fi_sanctions   # structured self-description
uv run crawler-core list --json                # machine-readable listing
```

Snapshots land at `data/<source_id>/<UTC-date>.json`.

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
| `fetch(url)` | Plain httpx GET | Anti-bot (FlareSolverr), JS rendering (Playwright), custom API auth |
| `discover_pages()` | Yields just `root_url` | Pagination — page numbers, cursor tokens, sitemap.xml, facet APIs |
| `classify(item)` | Wraps item with class `document_type`, no extractions | Site-specific typing, action extraction, entity extraction |

`parse_items()` is the only truly abstract method — every site's DOM/JSON
is different, and there's no useful default.

### Multiple crawlers per site

fi.se has 5 listings. Each is its own class:

```
src/crawler_core/sources/fi_se/
├── sanctions.py    → FiSanctionsCrawler   source_id="se_fi_sanctions"
├── reports.py      → FiReportsCrawler     source_id="se_fi_reports"
├── decisions.py    → FiDecisionsCrawler   source_id="se_fi_decisions"
├── news.py         → FiNewsCrawler        source_id="se_fi_news"
└── remissvar.py    → FiRemissvarCrawler   source_id="se_fi_remissvar"
```

Each is independent — one breaking doesn't affect the others.

## Layout

```
src/crawler_core/
├── base.py       Crawler ABC + @register + registry + orchestrator
├── models.py     FetchResult, RawItem, Record, Provenance, CrawlResult, ReviewFlag
├── http.py       httpx wrapper with browser-like default headers
├── cli.py        Typer: list, run, describe
└── sources/      One file per crawler, auto-imported recursively
    └── fi_se/
        └── sanctions.py
```

## What this is not (yet)

- **No health / scorecard / baseline verdicts.** Follow-up — the piece that
  makes a snapshot "trustworthy" rather than just "produced".
- **No FlareSolverr / Playwright helpers baked in.** Added the first time a
  site needs them, then subclasses can call the helper inside their `fetch()`.
- **No persistence beyond JSON snapshots.** Everything writes to
  `data/<source>/<date>.json`. Downstream storage lands when the framework
  graduates into a larger system.
