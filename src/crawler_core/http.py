"""HTTP helpers — the default fetch layer + specialized alternatives.

Two fetchers are available:

  * `http_get`         — plain httpx GET. Fast, no bells and whistles. Use
                         for sites that don't fingerprint the client.
  * `impersonate_get`  — curl_cffi with a Chrome TLS fingerprint. Use for
                         sites behind Cloudflare or other TLS-fingerprint
                         bot detection (FATF, etc.). Ships as a normal pip
                         dep — no Docker, no headless browser.

Subclasses that need one or the other override `Crawler.fetch()` and call
the appropriate helper.
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


def impersonate_get(
    url: str,
    timeout: float = 30.0,
    browser: str = "chrome",
) -> FetchResult:
    """HTTP GET that imitates a real browser's TLS fingerprint via curl_cffi.

    Use for sites behind Cloudflare or other TLS-fingerprint-based bot
    detection. Plain httpx fails with 403 on these; this passes because
    the TLS handshake looks like Chrome.

    Follows redirects, raises on 4xx/5xx.
    """
    # Imported lazily so users who don't need it don't pay the import cost.
    from curl_cffi import requests

    response = requests.get(
        url,
        impersonate=browser,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    return FetchResult(
        url=str(response.url),
        status_code=response.status_code,
        content=response.text,
        content_type=response.headers.get("content-type"),
        encoding=response.encoding,
    )
