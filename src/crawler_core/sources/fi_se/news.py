"""News and other published items (nyheter & övrigt publicerat) from fi.se."""

from __future__ import annotations

from typing import ClassVar

from crawler_core.base import register
from crawler_core.models import DocumentType
from crawler_core.sources.fi_se._base import FiSeListingCrawler


@register
class FiNewsCrawler(FiSeListingCrawler):
    source_id: ClassVar[str] = "se_fi_news"
    root_url: ClassVar[str] = "https://www.fi.se/sv/publicerat/nyheter--ovrigt-publicerat/"
    document_type: ClassVar[DocumentType] = "news"
