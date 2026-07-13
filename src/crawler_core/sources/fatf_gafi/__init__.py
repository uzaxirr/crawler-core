"""Crawlers for the Financial Action Task Force — fatf-gafi.org.

Publications on FATF's site are discovered via a JSON facet API
(`.../faceted_search/results.facets.json?offset=<N>&facet=<tag>`), not by
scraping the listing HTML. See `_base.py` for the shared listing crawler.
Each concrete facet — Guidance, Report, Recommendations, Risk Based
Approach — gets its own subclass file.

The site is behind Cloudflare. All FATF crawlers use `impersonate_get`
(curl_cffi + Chrome TLS fingerprint) via a `fetch()` override on the
intermediate base.
"""
