"""Consultation responses (remissvar) published by fi.se."""

from __future__ import annotations

from typing import ClassVar

from crawler_core.base import register
from crawler_core.models import DocumentType
from crawler_core.sources.fi_se._base import FiSeListingCrawler


@register
class FiRemissvarCrawler(FiSeListingCrawler):
    source_id: ClassVar[str] = "se_fi_remissvar"
    root_url: ClassVar[str] = "https://www.fi.se/sv/publicerat/remissvar/"
    document_type: ClassVar[DocumentType] = "consultation"
