"""Sanctions of financial companies, published by fi.se.

Extraction rules:
  * document_type = 'sanction' if URL contains the sanctions section prefix
  * actions       = keyword match against known Swedish sanction verbs
  * entity        = regex match against known headline shapes
                    ("FI ger X en anmärkning…", "FI återkallar tillståndet för X", …)
"""

from __future__ import annotations

import re
from datetime import date
from typing import ClassVar, Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler_core.base import Crawler, register
from crawler_core.models import (
    DocumentType,
    FetchResult,
    Provenance,
    RawItem,
    Record,
)


_ACTION_KEYWORDS: list[tuple[str, str]] = [
    ("återkallar tillståndet", "revocation"),
    ("sanktionsavgift", "fine"),
    ("straffavgift", "penalty"),
    ("varning", "warning"),
    ("anmärkning", "remark"),
    ("ingriper", "intervention"),
]

_ENTITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"^FI ger (.+?) (?:en|ett) (?:anmärkning(?:ar|er)?|varning|sanktionsavgift)",
            re.IGNORECASE,
        ),
        "regex:FI_ger_ENTITY",
    ),
    (
        re.compile(
            r"^FI återkallar tillståndet för (.+?)(?:\s+från|\s*$|,|\.)",
            re.IGNORECASE,
        ),
        "regex:FI_revocation_for_ENTITY",
    ),
    (
        re.compile(
            r"^(.+?) får en (?:anmärkning|varning|sanktionsavgift)",
            re.IGNORECASE,
        ),
        "regex:ENTITY_receives_action",
    ),
]

_SANCTIONS_PREFIX = "/sv/publicerat/sanktioner/finansiella-foretag/"


@register
class FiSanctionsCrawler(Crawler):
    source_id: ClassVar[str] = "se_fi_sanctions"
    root_url: ClassVar[str] = (
        "https://www.fi.se/sv/publicerat/sanktioner/finansiella-foretag/"
    )
    language: ClassVar[str] = "sv"
    document_type: ClassVar[DocumentType] = "sanction"

    # Walk up to 5 pages via ?page=N. The orchestrator's zero-new-URLs
    # termination catches fi.se's known no-op pagination.
    _max_pages: ClassVar[int] = 5

    def discover_pages(self) -> Iterator[tuple[str, str]]:
        for page in range(1, self._max_pages + 1):
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

    def classify(self, item: RawItem) -> tuple[Record, list[str]]:
        warnings: list[str] = []

        # Document type via URL prefix
        if _SANCTIONS_PREFIX in item.url:
            doc_type: DocumentType = "sanction"
            doc_rule = f"url_pattern:{_SANCTIONS_PREFIX}"
        else:
            doc_type = "other"
            doc_rule = "fallback:no_matching_url_pattern"
            warnings.append(f"document_type fell back to 'other' — {doc_rule}")

        # Actions via keyword scan on title + brief
        haystack = f"{item.title} {item.brief or ''}".lower()
        actions: list[str] = []
        action_rules: list[str] = []
        for keyword, action in _ACTION_KEYWORDS:
            if keyword in haystack:
                actions.append(action)
                action_rules.append(f"keyword:{keyword}={action}")

        # Entity via regex on title
        entity: str | None = None
        entity_rule: str | None = None
        for pattern, rule in _ENTITY_PATTERNS:
            match = pattern.match(item.title)
            if match:
                entity = match.group(1).strip()
                entity_rule = rule
                break

        record = Record(
            url=item.url,
            title=item.title,
            published_at=item.published_at,
            source_categories=item.source_categories,
            brief=item.brief,
            language=self.language,
            document_type=doc_type,
            actions=actions,
            entity=entity,
            provenance=Provenance(
                document_type_rule=doc_rule,
                actions_rules=action_rules,
                entity_rule=entity_rule,
            ),
        )
        return record, warnings


def _parse_iso_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
