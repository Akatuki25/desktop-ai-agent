"""DuckDuckGo HTML search provider.

Hits the html.duckduckgo.com endpoint that DuckDuckGo provides
specifically for scrape-friendly access. No API key, no rate-limiting
headaches as long as we behave like a normal browser.

The HTML contract is intentionally narrow — class names like
``.result__title`` / ``.result__snippet`` / ``.result__url`` are the
documented selectors. They've been stable for years; if DDG changes
them this module is the single place to update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

_DDG_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


class WebSearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> list[SearchHit]: ...


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG wraps result URLs in /l/?uddg=<encoded>. Recover the real URL."""
    if "uddg=" not in href:
        return href
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    target = qs.get("uddg", [""])[0]
    return target or href


class DuckDuckGoProvider:
    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, object] = {
            "timeout": self._timeout_s,
            "headers": {"User-Agent": _USER_AGENT},
            "follow_redirects": True,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if not query.strip():
            return []
        async with self._client() as client:
            resp = await client.post(_DDG_URL, data={"q": query})
            resp.raise_for_status()
            html = resp.text

        return self._parse(html, limit)

    @staticmethod
    def _parse(html: str, limit: int) -> list[SearchHit]:
        tree = HTMLParser(html)
        hits: list[SearchHit] = []
        for result in tree.css(".result"):
            title_node = result.css_first(".result__title")
            snippet_node = result.css_first(".result__snippet")
            link_node = result.css_first(".result__a") or title_node
            if not (title_node and link_node):
                continue
            href = link_node.attributes.get("href", "") or ""
            url = _unwrap_ddg_redirect(href)
            title = (title_node.text() or "").strip()
            snippet = (snippet_node.text() if snippet_node else "").strip()
            if not (title and url):
                continue
            hits.append(SearchHit(title=title, url=url, snippet=snippet))
            if len(hits) >= limit:
                break
        return hits
