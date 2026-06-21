"""Interop adapters for Promptetheus.

Adapters are thin layers over the public promptetheus.Session API. They
translate framework-specific events into the standard event helpers and never add
adapter-only event types or server behavior.

Optional dependencies (Playwright, OpenAI, Anthropic, LangChain) are imported
lazily inside each adapter module, so importing this package — or any single
adapter — never requires the other extras to be installed. The adapter classes
are resolved on attribute access via __getattr__ so a partially-installed
environment can still import the ones it needs.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public adapter name -> submodule that defines it.
_ADAPTER_MODULES = {
    "PlaywrightAdapter": "playwright",
    "OpenAIAdapter": "openai",
    "AnthropicAdapter": "anthropic",
    "PromptetheusCallbackHandler": "langchain",
    "LlamaIndexAdapter": "llamaindex",
    "CrewAIAdapter": "crewai",
    "OpenTelemetryBridge": "otel",
    "LangGraphAdapter": "langgraph",
    "LiteLLMAdapter": "litellm",
    "AutoGenAdapter": "autogen",
    "DSPyAdapter": "dspy",
    "HaystackAdapter": "haystack",
    "PydanticAIAdapter": "pydantic_ai",
}

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .anthropic import AnthropicAdapter as AnthropicAdapter
    from .autogen import AutoGenAdapter as AutoGenAdapter
    from .crewai import CrewAIAdapter as CrewAIAdapter
    from .dspy import DSPyAdapter as DSPyAdapter
    from .haystack import HaystackAdapter as HaystackAdapter
    from .langchain import PromptetheusCallbackHandler as PromptetheusCallbackHandler
    from .langgraph import LangGraphAdapter as LangGraphAdapter
    from .litellm import LiteLLMAdapter as LiteLLMAdapter
    from .llamaindex import LlamaIndexAdapter as LlamaIndexAdapter
    from .openai import OpenAIAdapter as OpenAIAdapter
    from .otel import OpenTelemetryBridge as OpenTelemetryBridge
    from .playwright import PlaywrightAdapter as PlaywrightAdapter
    from .pydantic_ai import PydanticAIAdapter as PydanticAIAdapter


def __getattr__(name: str) -> Any:
    module = _ADAPTER_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f".{module}", __name__), name)


def __dir__() -> list[str]:
    return sorted(_ADAPTER_MODULES)


__all__ = list(_ADAPTER_MODULES)
