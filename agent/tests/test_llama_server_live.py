"""Live integration tests against a real llama-server.

These are skipped by default. To run them, start llama-server with the
project's GGUF model and export the URL:

    & $env:LLAMA_SERVER_BIN -m $env:LLAMA_MODEL --port 8765 --jinja
    $env:LLAMA_SERVER_URL = "http://127.0.0.1:8765"
    $env:RUN_LLM_INTEGRATION = "1"
    cd agent
    uv run pytest tests/test_llama_server_live.py -v

Whoever sets RUN_LLM_INTEGRATION owns asserting that an LLM is actually
reachable; the tests fail loudly if it isn't, instead of silently
skipping. CI does not set the variable, so it stays out of the default
verify path.
"""

from __future__ import annotations

import os

import pytest

from agent.llm import LlamaServerBackend
from agent.llm.backend import Message

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_INTEGRATION") != "1",
    reason="set RUN_LLM_INTEGRATION=1 (and LLAMA_SERVER_URL) to run live LLM tests",
)


@pytest.mark.asyncio
async def test_real_llama_server_returns_non_empty_reply() -> None:
    url = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8765")
    backend = LlamaServerBackend(base_url=url)

    main_pieces: list[str] = []
    async for chunk in backend.chat_stream(
        [
            Message(role="system", content="You are a terse assistant."),
            Message(role="user", content="Reply with the single word: pong"),
        ]
    ):
        if chunk.done:
            break
        if not chunk.is_thinking:
            main_pieces.append(chunk.text)

    full = "".join(main_pieces).strip()
    assert full, f"expected a non-empty reply from llama-server at {url}"
    # Don't assert the exact word — the model may add punctuation; just
    # require the substring to appear so the assertion isn't brittle.
    assert "pong" in full.lower(), f"unexpected reply: {full!r}"
