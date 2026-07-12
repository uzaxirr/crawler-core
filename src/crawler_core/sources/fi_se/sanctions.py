"""Sanctions of financial companies, published by fi.se.

Extraction rules (added on top of the shared fi.se DOM parser):
  * document_type = 'sanction' if URL contains the sanctions section prefix
  * actions       = keyword match against known Swedish sanction verbs
  * entity        = regex match against known headline shapes
                    ("FI ger X en anmärkning…", "FI återkallar tillståndet för X", …)
"""

from __future__ import annotations

import re
from typing import ClassVar

from crawler_core.base import register
from crawler_core.models import DocumentType, Provenance, RawItem, Record
from crawler_core.sources.fi_se._base import FiSeListingCrawler


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
class FiSanctionsCrawler(FiSeListingCrawler):
    source_id: ClassVar[str] = "se_fi_sanctions"
    root_url: ClassVar[str] = (
        "https://www.fi.se/sv/publicerat/sanktioner/finansiella-foretag/"
    )
    document_type: ClassVar[DocumentType] = "sanction"

    def classify(self, item: RawItem) -> tuple[Record, list[str]]:
        warnings: list[str] = []

        if _SANCTIONS_PREFIX in item.url:
            doc_type: DocumentType = "sanction"
            doc_rule = f"url_pattern:{_SANCTIONS_PREFIX}"
        else:
            doc_type = "other"
            doc_rule = "fallback:no_matching_url_pattern"
            warnings.append(f"document_type fell back to 'other' — {doc_rule}")

        haystack = f"{item.title} {item.brief or ''}".lower()
        actions: list[str] = []
        action_rules: list[str] = []
        for keyword, action in _ACTION_KEYWORDS:
            if keyword in haystack:
                actions.append(action)
                action_rules.append(f"keyword:{keyword}={action}")

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
