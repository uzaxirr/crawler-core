"""HTTP helpers — the default fetch layer.

Subclasses that need Cloudflare bypass, JS rendering, or a custom auth
client override `Crawler.fetch()` and call a different helper (or their
own). This module stays the "plain HTTP" recipe.
"""

from __future__ import annotations

import httpx

from crawler_core.models import FetchResult


DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,sv;q=0.8,da;q=0.7,nb;q=0.6",
}


def http_get(url: str, timeout: float = 30.0) -> FetchResult:
    """Plain HTTP GET with browser-like default headers.

    Follows redirects, raises on 4xx/5xx. Returns the response body wrapped
    in a FetchResult so parse_items() can see the resolved URL.
    """
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=DEFAULT_HEADERS,
    ) as client:
        response = client.get(url)
    response.raise_for_status()
    return FetchResult(
        url=str(response.url),
        status_code=response.status_code,
        content=response.text,
        content_type=response.headers.get("content-type"),
        encoding=response.encoding,
    )
