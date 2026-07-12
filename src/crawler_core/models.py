"""Pydantic models — the data shapes that flow between crawler layers.

Layer boundaries the models mark:

    fetch()        -> FetchResult    (bytes + metadata about the request)
    parse_items()  -> [RawItem]      (unstructured discoveries from a page)
    classify()     -> Record         (typed, structured, with Provenance)
    crawl()        -> CrawlResult    (a whole snapshot)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


DocumentType = Literal[
    "sanction",
    "report",
    "decision",
    "guidance",
    "regulation",
    "consultation",
    "recommendation",
    "news",
    "publication",
    "other",
]


class FetchResult(BaseModel):
    """What a fetcher hands back to the parser.

    `url` is the final URL after redirects — use it as the base for urljoin
    inside parse_items().
    """

    url: str
    status_code: int
    content: str
    content_type: str | None = None
    encoding: str | None = None


class RawItem(BaseModel):
    """A single item pulled from a listing page, pre-classification.

    Every crawler produces these from parse_items(). The classify() step
    turns them into Records.

    `extra` is a free-form escape hatch for site-specific fields the parser
    picked up that the classifier will consume (e.g. a facet key on FATF).
    """

    url: str
    title: str
    published_at: date | None = None
    source_categories: list[str] = Field(default_factory=list)
    brief: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class Provenance(BaseModel):
    """Why does this Record have the values it does?

    Every derived field points at a rule id — a URL-prefix match, a keyword
    hit, a regex name. If a value looks wrong, this tells you which rule to
    inspect. No guessing.
    """

    document_type_rule: str
    actions_rules: list[str] = Field(default_factory=list)
    entity_rule: str | None = None


class Record(BaseModel):
    """A classified item ready for downstream storage or evaluation."""

    url: str
    title: str
    published_at: date | None
    source_categories: list[str]
    brief: str | None
    language: str

    document_type: DocumentType
    actions: list[str]
    entity: str | None

    pdf_urls: list[str] = Field(default_factory=list)

    provenance: Provenance


class ReviewFlag(BaseModel):
    """Something the classifier wasn't confident about — surface for a human."""

    url: str
    reason: str


class CrawlResult(BaseModel):
    """One end-to-end run of one crawler."""

    source_id: str
    crawled_at: datetime
    pages_fetched: int
    records: list[Record]
    review_queue: list[ReviewFlag]

    @property
    def record_count(self) -> int:
        return len(self.records)
