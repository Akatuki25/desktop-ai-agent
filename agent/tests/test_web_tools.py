"""Web tool tests — DDG search parser, fetch, open."""

from __future__ import annotations

import httpx
import pytest

from agent.integrations.ddg_search import DuckDuckGoProvider, _unwrap_ddg_redirect
from agent.tools.web_tools import WebFetchTool, WebOpenTool, WebSearchTool

# A small representative chunk of html.duckduckgo.com output.  Class
# names are the documented selectors and have been stable; if DDG
# changes the layout this fixture is the regression boundary.
_DDG_HTML = """\
<html><body>
  <div class="result">
    <a class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.rust-lang.org%2F&amp;rut=x">
      <h2 class="result__title">The Rust Programming Language</h2>
    </a>
    <a class="result__url" href="https://www.rust-lang.org/">www.rust-lang.org</a>
    <span class="result__snippet">A language empowering everyone to build reliable software.</span>
  </div>
  <div class="result">
    <a class="result__a" href="https://blog.rust-lang.org/">
      <h2 class="result__title">Rust Blog</h2>
    </a>
    <span class="result__snippet">Empowering everyone to build reliable software.</span>
  </div>
  <div class="result no-link"><span>filler without anchor — must be skipped</span></div>
</body></html>
"""


def test_unwrap_ddg_redirect_decodes_target() -> None:
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpath&rut=x"
    assert _unwrap_ddg_redirect(href) == "https://example.com/path"


def test_unwrap_ddg_redirect_passes_through_plain_url() -> None:
    assert _unwrap_ddg_redirect("https://example.com/") == "https://example.com/"


@pytest.mark.asyncio
async def test_ddg_search_parses_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "html.duckduckgo.com" in str(request.url)
        return httpx.Response(200, text=_DDG_HTML)

    provider = DuckDuckGoProvider(transport=httpx.MockTransport(handler))
    hits = await provider.search("rust", limit=5)

    assert len(hits) == 2
    assert hits[0].title == "The Rust Programming Language"
    # uddg= redirect was unwrapped
    assert hits[0].url == "https://www.rust-lang.org/"
    assert "reliable software" in hits[0].snippet
    assert hits[1].title == "Rust Blog"


@pytest.mark.asyncio
async def test_ddg_search_respects_limit() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_DDG_HTML)

    provider = DuckDuckGoProvider(transport=httpx.MockTransport(handler))
    hits = await provider.search("rust", limit=1)
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_ddg_search_empty_query_returns_empty_list() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, text=""))
    provider = DuckDuckGoProvider(transport=transport)
    assert await provider.search("") == []
    assert await provider.search("   ") == []


@pytest.mark.asyncio
async def test_web_search_tool_returns_dicts() -> None:
    class FakeProvider:
        async def search(self, query: str, limit: int = 5):
            from agent.integrations.ddg_search import SearchHit

            return [SearchHit(title="t", url="u", snippet="s")]

    tool = WebSearchTool(provider=FakeProvider())
    out = await tool.execute({"query": "x"})
    assert out == [{"title": "t", "url": "u", "snippet": "s"}]


def test_web_search_tool_schema_declares_required_query() -> None:
    schema = WebSearchTool().parameters_schema()
    assert "query" in schema["required"]
    assert schema["properties"]["limit"]["default"] == 5


@pytest.mark.asyncio
async def test_web_fetch_extracts_visible_text() -> None:
    html = """
    <html><head><title>t</title>
      <script>console.log('drop me')</script>
      <style>.x{}</style>
    </head><body>
      <nav>menu</nav>
      <article>
        <h1>Hello</h1>
        <p>This is a paragraph.</p>
      </article>
      <footer>copyright</footer>
    </body></html>
    """

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    tool = WebFetchTool(transport=httpx.MockTransport(handler))
    result = await tool.execute({"url": "https://example.com/"})

    assert result["ok"] is True
    text = result["text"]
    assert "Hello" in text
    assert "This is a paragraph." in text
    # script / style / nav / footer were stripped
    assert "console.log" not in text
    assert "menu" not in text
    assert "copyright" not in text


@pytest.mark.asyncio
async def test_web_fetch_rejects_non_http_url() -> None:
    tool = WebFetchTool()
    result = await tool.execute({"url": "file:///etc/passwd"})
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_web_fetch_truncates_very_long_pages() -> None:
    big = "abcdef\n" * 5000  # ~35k chars
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<html><body>{big}</body></html>")

    tool = WebFetchTool(transport=httpx.MockTransport(handler))
    result = await tool.execute({"url": "https://example.com/"})
    assert result["ok"] is True
    assert len(result["text"]) <= 8200  # 8000 + "(truncated)" tail


@pytest.mark.asyncio
async def test_web_fetch_reports_http_errors() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    tool = WebFetchTool(transport=httpx.MockTransport(handler))
    result = await tool.execute({"url": "https://example.com/missing"})
    assert result["ok"] is False
    assert result["status"] == 404


@pytest.mark.asyncio
async def test_web_open_rejects_non_http_url() -> None:
    tool = WebOpenTool()
    result = await tool.execute({"url": "file:///c:/secret"})
    assert result["ok"] is False
