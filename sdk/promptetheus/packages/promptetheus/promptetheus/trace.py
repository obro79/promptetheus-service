"""Public trace namespace."""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, MutableMapping
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import get_config
from .session import Session
from .transport import DurableHTTPTransport, InMemoryTransport, LocalSpoolTransport

_LOCALHOST_PROBE = "http://127.0.0.1:4318"


def _localhost_health_ok(base_url: str = _LOCALHOST_PROBE) -> bool:
    """Return True when a Promptetheus API responds on localhost:4318."""

    try:
        request = Request(f"{base_url.rstrip('/')}/health", method="GET")
        with urlopen(request, timeout=0.5) as response:
            return int(getattr(response, "status", 200)) == 200
    except (URLError, OSError, ValueError, TimeoutError):
        return False


def _resolved_endpoint(endpoint: str | None) -> str | None:
    """Endpoint precedence: explicit arg > env var > config file > hosted default."""

    return endpoint or os.environ.get("PROMPTETHEUS_API_URL") or get_config().api_url


def _resolved_api_key(api_key: str | None) -> str | None:
    """API-key precedence: explicit arg > env var > config file > None."""

    return api_key or os.environ.get("PROMPTETHEUS_API_KEY") or get_config().api_key


def resolve_transport(
    transport: Any | None = "auto",
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    spool_dir: str = ".promptetheus/spool",
) -> Any:
    """Resolve user transport config into a transport object.

    Dependency-free defaults keep early adoption simple: use hosted HTTP when
    an API key is configured, otherwise write a local spool that can be replayed
    through FastAPI later. Endpoint values fall back to
    ~/.promptetheus/config.toml and then the hosted Promptetheus API URL.
    """

    if transport is None or transport == "auto":
        resolved_api_key = _resolved_api_key(api_key)
        if not resolved_api_key:
            return LocalSpoolTransport(spool_dir)
        resolved_endpoint = _resolved_endpoint(endpoint)
        if not resolved_endpoint and _localhost_health_ok():
            resolved_endpoint = _LOCALHOST_PROBE
        if resolved_endpoint:
            return DurableHTTPTransport(
                resolved_endpoint,
                api_key=resolved_api_key,
                spool_dir=spool_dir,
            )
        return LocalSpoolTransport(spool_dir)
    if transport == "http":
        resolved_endpoint = _resolved_endpoint(endpoint)
        resolved_api_key = _resolved_api_key(api_key)
        if not resolved_endpoint:
            raise ValueError(
                "transport='http' requires endpoint or PROMPTETHEUS_API_URL"
            )
        if not resolved_api_key:
            raise ValueError(
                "transport='http' requires api_key or PROMPTETHEUS_API_KEY"
            )
        return DurableHTTPTransport(
            resolved_endpoint,
            api_key=resolved_api_key,
            spool_dir=spool_dir,
        )
    if transport == "spool":
        return LocalSpoolTransport(spool_dir)
    if transport == "memory":
        return InMemoryTransport()
    return transport


def start(
    *,
    agent: str,
    user_goal: str,
    session_id: str | None = None,
    project_id: str | None = None,
    api_key: str | None = None,
    environment: str | None = None,
    transport: Any | None = None,
    endpoint: str | None = None,
    spool_dir: str = ".promptetheus/spool",
    redact: Callable[[MutableMapping[str, Any]], MutableMapping[str, Any] | None]
    | str
    | None = None,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
    sample_rate: float | None = None,
    tail_sample: bool = False,
    event_sample_rates: Mapping[str, float] | None = None,
    tail_policy: Any | None = None,
    **_: Any,
) -> Session:
    """Start a Promptetheus session.

    transport="auto" sends to the hosted/default endpoint when a project API
    key is present and otherwise spools events locally. sample_rate and redact
    fall back to config (env / ~/.promptetheus/config.toml); redact="default"
    enables the built-in secret/PII redactor.
    """

    _config = get_config()
    effective_sample_rate = _config.sample_rate if sample_rate is None else sample_rate
    effective_redact = _config.redact if redact is None else redact
    effective_environment = (
        environment if environment is not None else _config.environment
    )
    effective_project_id = project_id if project_id is not None else _config.project_id

    return Session(
        agent=agent,
        user_goal=user_goal,
        session_id=session_id,
        project_id=effective_project_id,
        environment=effective_environment,
        transport=resolve_transport(
            transport, endpoint=endpoint, api_key=api_key, spool_dir=spool_dir
        ),
        redact=effective_redact,
        metadata=metadata,
        tags=tags,
        sample_rate=effective_sample_rate,
        tail_sample=tail_sample,
        event_sample_rates=event_sample_rates,
        tail_policy=tail_policy,
    )
