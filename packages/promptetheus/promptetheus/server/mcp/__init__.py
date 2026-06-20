"""Promptetheus incident-context MCP server (thin HTTP client of FastAPI).

Importing this package never requires the optional ``mcp`` or ``httpx``
dependencies; both are imported lazily where they are used.
"""

from __future__ import annotations

from .client import PromptetheusAPIError, PromptetheusClient
from .server import build_server, run

__all__ = [
    "PromptetheusAPIError",
    "PromptetheusClient",
    "build_server",
    "run",
]
