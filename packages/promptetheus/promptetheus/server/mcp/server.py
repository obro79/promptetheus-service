"""Promptetheus incident-context MCP server.

Exposes six read-only tools and one write tool to a coding agent (Cursor / Claude
Code) over MCP stdio. Each tool is a thin call into PromptetheusClient, which is a
client of the FastAPI gateway — the gateway owns workspace scoping and redaction,
so secrets never reach the agent.

The tool bodies are plain module-level functions taking a PromptetheusClient, so
they are unit-testable without the ``mcp`` SDK installed. build_server registers
them on a FastMCP server, lazy-importing the SDK so importing this module never
requires the optional ``mcp`` extra (same pattern as the adapters/exporters).
"""

from __future__ import annotations

from typing import Any

from .client import PromptetheusClient

SERVER_NAME = "promptetheus"


# ---------------------------------------------------------------------------
# Tool implementations (read-only unless noted)
# ---------------------------------------------------------------------------


def get_incident(client: PromptetheusClient, incident_id: str) -> dict[str, Any]:
    """Return the incident summary row (status, label, severity, owner, PR link)."""

    return client.get_incident(incident_id)


def get_failure_evidence(
    client: PromptetheusClient, incident_id: str
) -> dict[str, Any]:
    """Return the redacted failure evidence: detector labels, evidence chips,
    root cause, the critical step seq, and the redacted events around it."""

    context = client.get_incident_context(incident_id)
    return {
        "incident_id": incident_id,
        "labels": context.get("labels"),
        "evidence": context.get("evidence"),
        "root_cause": context.get("root_cause"),
        "critical_step_seq": context.get("critical_step_seq"),
        "events": context.get("events"),
    }


def get_replay_timeline(
    client: PromptetheusClient, incident_id: str
) -> dict[str, Any]:
    """Return the replay artifact signed URL plus the per-seq event time map."""

    context = client.get_incident_context(incident_id)
    replay = dict(context.get("replay") or {})
    replay["incident_id"] = incident_id
    replay["critical_step_seq"] = context.get("critical_step_seq")
    return replay


def get_regression_case(
    client: PromptetheusClient, incident_id: str
) -> dict[str, Any]:
    """Return the latest regression case (before/after pass/fail) for the incident."""

    context = client.get_incident_context(incident_id)
    return {
        "incident_id": incident_id,
        "regression_case": context.get("regression_case"),
    }


def search_similar_incidents(
    client: PromptetheusClient, query: str
) -> dict[str, Any]:
    """Return incidents whose label/severity/status match query (case-insensitive)."""

    return {"query": query, "incidents": client.search_incidents(query)}


def get_connected_repo(
    client: PromptetheusClient, project_id: str
) -> dict[str, Any]:
    """Return the connected-repo descriptor (repo + allowed_paths) for a project."""

    return client.get_connected_repo(project_id)


def link_pr_to_incident(
    client: PromptetheusClient, incident_id: str, pr_url: str
) -> dict[str, Any]:
    """Attach a pull-request URL to an incident. This is the only mutating tool."""

    return client.link_pr_to_incident(incident_id, pr_url)


# ---------------------------------------------------------------------------
# FastMCP wiring
# ---------------------------------------------------------------------------


def _load_fastmcp() -> Any:
    """Import FastMCP, or raise a clear missing-extra error (lazy, like adapters)."""

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The Promptetheus MCP server requires the optional 'mcp' extra. "
            "Install it with: pip install 'promptetheus[mcp]'"
        ) from exc
    return FastMCP


def build_server(client: PromptetheusClient | None = None) -> Any:
    """Build a FastMCP server with the seven incident-context tools registered.

    Args:
        client: An optional PromptetheusClient (tests inject one wired to an
            in-process app). Defaults to one built from the environment.

    Returns:
        A configured FastMCP instance ready to run over stdio.
    """

    fast_mcp = _load_fastmcp()
    api = client if client is not None else PromptetheusClient()
    server = fast_mcp(SERVER_NAME)

    @server.tool(name="get_incident", description=get_incident.__doc__)
    def _get_incident(incident_id: str) -> dict[str, Any]:
        return get_incident(api, incident_id)

    @server.tool(
        name="get_failure_evidence", description=get_failure_evidence.__doc__
    )
    def _get_failure_evidence(incident_id: str) -> dict[str, Any]:
        return get_failure_evidence(api, incident_id)

    @server.tool(name="get_replay_timeline", description=get_replay_timeline.__doc__)
    def _get_replay_timeline(incident_id: str) -> dict[str, Any]:
        return get_replay_timeline(api, incident_id)

    @server.tool(name="get_regression_case", description=get_regression_case.__doc__)
    def _get_regression_case(incident_id: str) -> dict[str, Any]:
        return get_regression_case(api, incident_id)

    @server.tool(
        name="search_similar_incidents",
        description=search_similar_incidents.__doc__,
    )
    def _search_similar_incidents(query: str) -> dict[str, Any]:
        return search_similar_incidents(api, query)

    @server.tool(name="get_connected_repo", description=get_connected_repo.__doc__)
    def _get_connected_repo(project_id: str) -> dict[str, Any]:
        return get_connected_repo(api, project_id)

    @server.tool(name="link_pr_to_incident", description=link_pr_to_incident.__doc__)
    def _link_pr_to_incident(incident_id: str, pr_url: str) -> dict[str, Any]:
        return link_pr_to_incident(api, incident_id, pr_url)

    return server


def run() -> None:
    """Boot the incident-context MCP server over stdio."""

    build_server().run()


__all__ = [
    "SERVER_NAME",
    "build_server",
    "get_connected_repo",
    "get_failure_evidence",
    "get_incident",
    "get_regression_case",
    "get_replay_timeline",
    "link_pr_to_incident",
    "run",
    "search_similar_incidents",
]
