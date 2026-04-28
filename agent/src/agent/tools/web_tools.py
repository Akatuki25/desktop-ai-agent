"""Web tools — search, fetch, and open-in-browser.

Phase scope (this commit, issue #42):
- ``web.search`` via DuckDuckGo HTML scrape (no API key required)
- ``web.fetch`` minimal HTTP-only implementation that returns the
  body text. Will be replaced by a Playwright worker in a later
  phase for JS-rendered pages and cleaner article extraction.
- ``web.open`` uses the OS default browser via stdlib ``webbrowser``.
  The agent cannot read the page that opens — this is a "show the
  user something" tool, not a research tool.

All three are risk=low; ``web.fetch`` returns potentially untrusted
content, so callers should wrap the result with the
``[UNTRUSTED source=<url>]…[/UNTRUSTED]`` envelope when injecting
back into the LLM context (issue #44).
"""

from __future__ import annotations

import webbrowser
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from agent.integrations.ddg_search import DuckDuckGoProvider, WebSearchProvider
from agent.tools.base import Tool

_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_FETCH_MAX_CHARS = 8000  # cap injected text so we don't blow the context window


class WebSearchTool(Tool):
    name = "web.search"
    description = (
        "DuckDuckGo でキーワード Web 検索を行う。返却は title / url / "
        "snippet の配列。Web 上の最新情報や知らないトピックを調べたい時に使う。"
    )
    risk = "low"
    requires_confirmation = False

    def __init__(self, provider: WebSearchProvider | None = None) -> None:
        self._provider = provider or DuckDuckGoProvider()

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "検索キーワード"},
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        query = str(args.get("query", ""))
        limit = int(args.get("limit", 5))
        hits = await self._provider.search(query, limit=limit)
        return [
            {"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits
        ]


class WebFetchTool(Tool):
    name = "web.fetch"
    description = (
        "URL を取得して本文テキストを返す。検索結果から興味あるページを開いて"
        "中身を確認したい時に使う。HTML タグは除去され、最大 8000 文字までに切り詰める。"
    )
    risk = "low"
    requires_confirmation = False

    def __init__(
        self,
        *,
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._transport = transport

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "取得する URL (http/https)"},
            },
        }

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, object] = {
            "timeout": self._timeout_s,
            "headers": {"User-Agent": _FETCH_USER_AGENT},
            "follow_redirects": True,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]

    async def execute(self, args: dict[str, Any]) -> Any:
        url = str(args.get("url", ""))
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "URL must be http(s)://"}

        async with self._client() as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"ok": False, "url": url, "status": resp.status_code}

        text = _extract_text(resp.text)
        if len(text) > _FETCH_MAX_CHARS:
            text = text[:_FETCH_MAX_CHARS] + "\n…(truncated)"
        return {"ok": True, "url": str(resp.url), "text": text}


def _extract_text(html: str) -> str:
    """Drop scripts / styles / nav, then return the visible text."""
    tree = HTMLParser(html)
    for sel in ("script", "style", "noscript", "nav", "header", "footer"):
        for node in tree.css(sel):
            node.decompose()
    body = tree.css_first("body") or tree.root
    if body is None:
        return ""
    raw = body.text(separator="\n")
    # Collapse blank-line runs (DuckDuckGo / news sites have many).
    lines = [ln.strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln)


class WebOpenTool(Tool):
    name = "web.open"
    description = (
        "URL をユーザーの既定ブラウザで開く。エージェントは中身を読まない。"
        "ユーザーに直接見せたいページがある時のみ使う。"
    )
    risk = "low"
    requires_confirmation = False

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "開く URL"},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        url = str(args.get("url", ""))
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "URL must be http(s)://"}
        opened = webbrowser.open(url, new=2)
        return {"ok": bool(opened), "url": url}
