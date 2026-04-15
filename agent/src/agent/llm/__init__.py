"""LLM backend abstraction.

`LLMBackend` is the single interface the orchestrator talks to; the
concrete implementation can be llama-server (Phase 0+) or anything
else OpenAI-compatible. `FakeLLMBackend` exists for tests so we don't
need a running model.
"""

from agent.llm.backend import LLMBackend, LLMChunk, Message
from agent.llm.fake import FakeLLMBackend
from agent.llm.llama_server import LlamaServerBackend
from agent.llm.stream_parser import ThinkingStreamParser

__all__ = [
    "FakeLLMBackend",
    "LLMBackend",
    "LLMChunk",
    "LlamaServerBackend",
    "Message",
    "ThinkingStreamParser",
]
