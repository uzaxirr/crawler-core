"""FATF Risk Based Approach publications."""

from __future__ import annotations

from typing import ClassVar

from crawler_core.base import register
from crawler_core.models import DocumentType
from crawler_core.sources.fatf_gafi._base import FatfListingCrawler


@register
class FatfRiskBasedCrawler(FatfListingCrawler):
    source_id: ClassVar[str] = "int_fatf_riskbased"
    root_url: ClassVar[str] = "https://www.fatf-gafi.org/en/publications.html"
    document_type: ClassVar[DocumentType] = "guidance"
    facet: ClassVar[str] = "fatf-gafi-faft-doc types:tag-Risk Based Approach"
