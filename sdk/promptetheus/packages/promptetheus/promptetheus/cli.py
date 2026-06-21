"""CLI entry point for Promptetheus.

Commands:
    promptetheus dev       Boot the local FastAPI ingestion gateway on :4318.
    promptetheus version   Print the installed version.
    promptetheus doctor    Show resolved config, server reachability, spool backlog.
    promptetheus spool ... Inspect / replay / purge the local delivery spool.

The spool commands operate on the durable transport's local buffer
(.promptetheus/spool/<session>.jsonl for pending deliveries and
dead-letter/<session>.jsonl for permanently-rejected events). They never crash
with a traceback: missing dirs and unconfigured endpoints produce clear messages
and a nonzero exit where appropriate.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote

# Host/port for the local FastAPI ingestion gateway (see CLAUDE.md "Ports").
DEV_HOST = "0.0.0.0"
DEV_PORT = 4318

DEFAULT_SPOOL_DIR = ".promptetheus/spool"
DEFAULT_MCP_BASE_URL = "https://mcp.promptetheus.dev/promptetheus"
_DEAD_LETTER_DIR = "dead-letter"


def _run_dev() -> None:
    """Boot the FastAPI ingestion gateway on :4318 via uvicorn.

    Never raises: if uvicorn (or the server app) cannot be imported, print clear
    guidance instead of crashing, so promptetheus dev always exits cleanly.
    """

    try:
        import uvicorn
    except ImportError:
        print("promptetheus dev needs uvicorn to boot the FastAPI ingestion gateway.")
        print(
            "Install the server dependencies, e.g. pip install 'promptetheus[server]'."
        )
        print(f"Once installed, the gateway listens on http://{DEV_HOST}:{DEV_PORT}")
        return

    try:
        from .server.app import create_app
    except Exception as exc:  # pragma: no cover - defensive: never crash the CLI
        print("promptetheus dev could not import the FastAPI server app.")
        print(f"Reason: {exc}")
        print(
            "Install the server dependencies, e.g. pip install 'promptetheus[server]'."
        )
        return

    app = create_app()
    print(f"Starting Promptetheus ingestion gateway on http://{DEV_HOST}:{DEV_PORT}")
    uvicorn.run(app, host=DEV_HOST, port=DEV_PORT)


def _run_mcp() -> None:
    """Boot the incident-context MCP server over stdio.

    Never raises: a missing 'mcp' extra or an unset PROMPTETHEUS_API_KEY produce
    clear guidance instead of a traceback, so promptetheus mcp always exits cleanly.
    """

    try:
        from .server.mcp import run as run_mcp
    except Exception as exc:  # pragma: no cover - defensive: never crash the CLI
        print("promptetheus mcp could not import the MCP server module.")
        print(f"Reason: {exc}")
        print("Install the MCP dependencies, e.g. pip install 'promptetheus[mcp]'.")
        return

    try:
        run_mcp()
    except RuntimeError as exc:
        # Missing 'mcp' extra or missing PROMPTETHEUS_API_KEY surface here.
        print(str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="promptetheus")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "dev", help="Boot the local FastAPI ingestion gateway on :4318"
    )
    mcp_p = subparsers.add_parser(
        "mcp", help="Boot the incident-context MCP server over stdio"
    )
    mcp_sub = mcp_p.add_subparsers(dest="mcp_command")
    mcp_install_p = mcp_sub.add_parser(
        "install",
        help="Print hosted Promptetheus MCP client config for a Promptetheus project",
    )
    mcp_install_p.add_argument(
        "--client",
        choices=("codex", "claude", "cursor"),
        required=True,
        help="MCP client config format to print",
    )
    mcp_install_p.add_argument(
        "--workspace",
        required=True,
        help="Promptetheus workspace slug or id",
    )
    mcp_install_p.add_argument(
        "--project-ref",
        required=True,
        help="Promptetheus project ref to scope evidence reads",
    )
    mcp_install_p.add_argument(
        "--server-name",
        default="promptetheus",
        help="MCP server name in the generated client config",
    )
    mcp_install_p.add_argument(
        "--hosted-url",
        default=DEFAULT_MCP_BASE_URL,
        help=f"hosted MCP base URL (default {DEFAULT_MCP_BASE_URL})",
    )
    subparsers.add_parser("version", help="Print the installed Promptetheus version")
    init_p = subparsers.add_parser(
        "init",
        help="Bootstrap a Promptetheus project and print a generated API key",
    )
    init_p.add_argument(
        "--api-url",
        default=None,
        help="Promptetheus API URL (default: hosted API, or PROMPTETHEUS_API_URL)",
    )
    init_p.add_argument(
        "--console-token",
        default=None,
        help="Console auth token (default: PROMPTETHEUS_CONSOLE_TOKEN)",
    )
    init_p.add_argument(
        "--workspace-name",
        default="Promptetheus Workspace",
        help="Workspace name to create or reuse",
    )
    init_p.add_argument(
        "--project-name",
        default="Default Project",
        help="Project name to create or reuse",
    )
    init_p.add_argument(
        "--agent-name",
        default=None,
        help="Optional first agent name to associate with the project",
    )
    init_p.add_argument(
        "--write-env",
        nargs="?",
        const=".env",
        default=None,
        help="Write PROMPTETHEUS_API_KEY and PROMPTETHEUS_API_URL to an env file",
    )
    init_p.add_argument(
        "--write-config",
        action="store_true",
        help="Write api_key and api_url to ~/.promptetheus/config.toml",
    )
    subparsers.add_parser(
        "doctor", help="Show resolved config, server reachability, spool backlog"
    )

    spool = subparsers.add_parser(
        "spool", help="Inspect/replay/purge the local delivery spool"
    )
    spool.add_argument(
        "action",
        choices=("list", "replay", "purge"),
        help="list: show backlog; replay: re-send pending via the API; purge: delete spool files",
    )
    spool.add_argument(
        "--dir",
        default=DEFAULT_SPOOL_DIR,
        help=f"spool directory (default {DEFAULT_SPOOL_DIR})",
    )
    spool.add_argument(
        "--dead-letter",
        action="store_true",
        help="with purge: also delete dead-letter files (default keeps them)",
    )

    sessions_p = subparsers.add_parser("sessions", help="List locally spooled sessions")
    sessions_p.add_argument("--dir", default=DEFAULT_SPOOL_DIR)

    export_p = subparsers.add_parser(
        "export", help="Export a spooled session to a JSON file"
    )
    export_p.add_argument("session_id")
    export_p.add_argument("--dir", default=DEFAULT_SPOOL_DIR)
    export_p.add_argument("--out", default=None, help="output file (default: stdout)")

    replay_p = subparsers.add_parser(
        "replay",
        help="Print a session timeline (from a session id, .jsonl, or exported .json)",
    )
    replay_p.add_argument(
        "target", help="session id, a .jsonl spool file, or an exported .json file"
    )
    replay_p.add_argument("--dir", default=DEFAULT_SPOOL_DIR)
    replay_p.add_argument(
        "--tree",
        action="store_true",
        help="render the reconstructed run tree instead of a flat timeline",
    )

    diff_p = subparsers.add_parser(
        "diff", help="Diff two sessions and report added/removed/changed steps"
    )
    diff_p.add_argument("session_a", help="baseline session id or file")
    diff_p.add_argument("session_b", help="candidate session id or file")
    diff_p.add_argument("--dir", default=DEFAULT_SPOOL_DIR)

    fingerprint_p = subparsers.add_parser(
        "fingerprint", help="Print a session's failure fingerprint (for clustering)"
    )
    fingerprint_p.add_argument("target", help="session id or file")
    fingerprint_p.add_argument("--dir", default=DEFAULT_SPOOL_DIR)

    import_p = subparsers.add_parser(
        "import", help="Replay an exported session JSON through the API"
    )
    import_p.add_argument("file")

    args = parser.parse_args(argv)

    if args.command == "version":
        from . import __version__

        print(__version__)
        return 0
    if args.command == "dev":
        _run_dev()
        return 0
    if args.command == "init":
        return _cmd_init(
            api_url=args.api_url,
            console_token=args.console_token,
            workspace_name=args.workspace_name,
            project_name=args.project_name,
            agent_name=args.agent_name,
            write_env=Path(args.write_env) if args.write_env else None,
            write_config=args.write_config,
        )
    if args.command == "mcp":
        if getattr(args, "mcp_command", None) == "install":
            return _cmd_mcp_install(
                args.client,
                args.workspace,
                args.project_ref,
                args.server_name,
                args.hosted_url,
            )
        _run_mcp()
        return 0
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "spool":
        return _cmd_spool(
            args.action, Path(args.dir), include_dead_letter=args.dead_letter
        )
    if args.command == "sessions":
        return _cmd_sessions(Path(args.dir))
    if args.command == "export":
        return _cmd_export(args.session_id, Path(args.dir), args.out)
    if args.command == "replay":
        return _cmd_replay(args.target, Path(args.dir), tree=args.tree)
    if args.command == "diff":
        return _cmd_diff(args.session_a, args.session_b, Path(args.dir))
    if args.command == "fingerprint":
        return _cmd_fingerprint(args.target, Path(args.dir))
    if args.command == "import":
        return _cmd_import(Path(args.file))

    parser.print_help()
    return 0


# -- init -------------------------------------------------------------------


def _cmd_init(
    *,
    api_url: str | None,
    console_token: str | None,
    workspace_name: str,
    project_name: str,
    agent_name: str | None,
    write_env: Path | None,
    write_config: bool,
) -> int:
    from .config import DEFAULT_API_URL, DEFAULT_CONFIG_PATH

    resolved_api_url = (
        api_url or os.environ.get("PROMPTETHEUS_API_URL") or DEFAULT_API_URL
    ).rstrip("/")
    resolved_token = console_token or os.environ.get("PROMPTETHEUS_CONSOLE_TOKEN")

    if not resolved_token:
        print("Cannot bootstrap: no console token configured.")
        print("Set PROMPTETHEUS_CONSOLE_TOKEN or pass --console-token.")
        print()
        print("For local self-hosted development, the default dev token is:")
        print(
            "  promptetheus init --api-url http://127.0.0.1:4318 "
            "--console-token pt_console_token"
        )
        return 2

    payload = {
        "workspace_name": workspace_name,
        "project_name": project_name,
    }
    if agent_name:
        payload["agent_name"] = agent_name

    url = f"{resolved_api_url}/api/onboarding/bootstrap"
    status, body = _post_json(url, payload, bearer_token=resolved_token)
    if status < 200 or status >= 300:
        print(f"Promptetheus bootstrap failed ({status}).")
        detail = _response_detail(body)
        if detail:
            print(detail)
        return 1

    api_key = body.get("api_key") if isinstance(body, dict) else None
    project = body.get("project") if isinstance(body, dict) else None
    workspace = body.get("workspace") if isinstance(body, dict) else None
    project_name_out = _named_value(project, fallback=project_name)
    workspace_name_out = _named_value(workspace, fallback=workspace_name)

    if not api_key:
        preview = body.get("api_key_preview") if isinstance(body, dict) else None
        print(
            "Promptetheus project already exists, but the raw API key is not "
            "recoverable."
        )
        if preview:
            print(f"Existing key: {preview}")
        print(
            "Rotate the key in the dashboard, or create a new project name and "
            "run init again."
        )
        return 1

    print("Promptetheus project ready")
    print(f"  API URL  : {resolved_api_url}")
    print(f"  workspace: {workspace_name_out}")
    print(f"  project  : {project_name_out}")
    print()
    print("Save this key; it is shown once:")
    print(f"  {api_key}")
    print()
    print("For your shell:")
    print(f"  export PROMPTETHEUS_API_KEY={_shell_quote(api_key)}")
    if resolved_api_url != DEFAULT_API_URL:
        print(f"  export PROMPTETHEUS_API_URL={_shell_quote(resolved_api_url)}")

    if write_env is not None:
        _write_env_file(write_env, api_url=resolved_api_url, api_key=api_key)
        print(f"Wrote env vars to {write_env}.")
    if write_config:
        _write_config_file(
            DEFAULT_CONFIG_PATH, api_url=resolved_api_url, api_key=api_key
        )
        print(f"Wrote SDK config to {DEFAULT_CONFIG_PATH}.")
    return 0


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    bearer_token: str,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _parse_json_object(body)
    except error.URLError as exc:
        return 0, {"detail": f"Could not reach {url}: {exc.reason}"}
    except TimeoutError:
        return 0, {"detail": f"Timed out connecting to {url}"}


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"detail": text} if text else {}
    return parsed if isinstance(parsed, dict) else {"detail": parsed}


def _response_detail(body: dict[str, Any]) -> str:
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if detail:
        return json.dumps(detail)
    return ""


def _named_value(value: object, *, fallback: str) -> str:
    if isinstance(value, dict):
        name = value.get("name") or value.get("slug") or value.get("id")
        if name:
            return str(name)
    return fallback


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_env_file(path: Path, *, api_url: str, api_key: str) -> None:
    assignments = {
        "PROMPTETHEUS_API_KEY": api_key,
        "PROMPTETHEUS_API_URL": api_url,
    }
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in existing:
        stripped = line.lstrip()
        key = stripped.split("=", 1)[0] if "=" in stripped else ""
        if key in assignments and not stripped.startswith("#"):
            next_lines.append(f"{key}={_env_quote(assignments[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in assignments.items():
        if key not in seen:
            next_lines.append(f"{key}={_env_quote(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


def _env_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_config_file(path: Path, *, api_url: str, api_key: str) -> None:
    assignments = {
        "api_url": api_url,
        "api_key": api_key,
    }
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in existing:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in assignments and not stripped.startswith("#"):
            next_lines.append(f"{key} = {json.dumps(assignments[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in assignments.items():
        if key not in seen:
            next_lines.append(f"{key} = {json.dumps(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


# -- mcp install ------------------------------------------------------------


def _cmd_mcp_install(
    client: str,
    workspace: str,
    project_ref: str,
    server_name: str,
    hosted_url: str,
) -> int:
    if not workspace.strip():
        print("--workspace must not be empty")
        return 2
    if not project_ref.strip():
        print("--project-ref must not be empty")
        return 2
    if not server_name.strip():
        print("--server-name must not be empty")
        return 2

    url = _build_mcp_url(hosted_url, workspace, project_ref)
    print("Promptetheus hosted MCP")
    print(f"  URL        : {url}")
    print(f"  workspace  : {workspace}")
    print(f"  project_ref: {project_ref}")
    print("  access     : read-only Promptetheus evidence scoped to this project")
    print()

    if client == "codex":
        print("Codex config snippet:")
        print(_format_codex_mcp_config(server_name, url))
        return 0
    if client == "claude":
        print("Claude Desktop config snippet:")
        print(_format_json_mcp_config(server_name, url))
        return 0
    if client == "cursor":
        print("Cursor workspace .cursor/mcp.json snippet:")
        print(_format_json_mcp_config(server_name, url))
        return 0

    print(f"Unsupported MCP client: {client}")
    return 2


def _build_mcp_url(hosted_url: str, workspace: str, project_ref: str) -> str:
    base = hosted_url.rstrip("/")
    workspace_slug = quote(workspace.strip(), safe="")
    project_slug = quote(project_ref.strip(), safe="")
    return f"{base}/{workspace_slug}/{project_slug}"


def _format_codex_mcp_config(server_name: str, url: str) -> str:
    escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
    escaped_name = server_name.strip().replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join(
        (
            f'[mcp_servers."{escaped_name}"]',
            'command = "npx"',
            f'args = ["-y", "mcp-remote", "{escaped_url}"]',
        )
    )


def _format_json_mcp_config(server_name: str, url: str) -> str:
    return json.dumps(
        {
            "mcpServers": {
                server_name.strip(): {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", url],
                }
            }
        },
        indent=2,
    )


# -- doctor -----------------------------------------------------------------


def _cmd_doctor() -> int:
    from .config import load_config

    config = load_config()
    print("Promptetheus configuration:")
    print(f"  api_url      : {config.api_url or '(not set)'}")
    print(f"  api_key      : {'set' if config.api_key else '(not set)'}")
    print(f"  project_id   : {config.project_id or '(not set)'}")
    print(f"  environment  : {config.environment or '(not set)'}")
    print(f"  sample_rate  : {config.sample_rate}")
    print(f"  redact       : {config.redact or '(off)'}")

    pending, dead = _scan_spool(Path(DEFAULT_SPOOL_DIR))
    print(
        f"  spool backlog: {pending['events']} pending event(s) in "
        f"{pending['files']} file(s); {dead['events']} dead-lettered"
    )

    healthy = True
    if not config.api_key:
        print("Connectivity   : no api_key configured (set PROMPTETHEUS_API_KEY).")
        healthy = False
    elif not config.api_url:
        print(
            "Connectivity   : no api_url configured (set PROMPTETHEUS_API_URL or config.toml)."
        )
        healthy = False
    else:
        ok, detail = _check_health(config.api_url)
        print(f"Connectivity   : {'OK' if ok else 'UNREACHABLE'} ({detail})")
        healthy = healthy and ok

    return 0 if healthy else 1


# -- spool ------------------------------------------------------------------


def _cmd_spool(action: str, spool_dir: Path, *, include_dead_letter: bool) -> int:
    if action == "list":
        return _spool_list(spool_dir)
    if action == "replay":
        return _spool_replay(spool_dir)
    if action == "purge":
        return _spool_purge(spool_dir, include_dead_letter=include_dead_letter)
    print(f"Unknown spool action: {action}")
    return 2


def _spool_list(spool_dir: Path) -> int:
    if not spool_dir.exists():
        print(f"No spool directory at {spool_dir} — nothing pending.")
        return 0
    pending, dead = _scan_spool(spool_dir)
    print(f"Spool: {spool_dir}")
    print(
        f"  pending : {pending['events']} event(s) across {pending['files']} "
        f"session file(s), {pending['bytes']} bytes"
    )
    print(
        f"  dead    : {dead['events']} event(s) across {dead['files']} file(s), {dead['bytes']} bytes"
    )
    for name, count in sorted(pending["per_session"].items()):
        print(f"    {name}: {count} pending")
    return 0


def _spool_replay(spool_dir: Path) -> int:
    from .config import load_config

    config = load_config()
    if not config.api_key:
        print("Cannot replay: no api_key configured (set PROMPTETHEUS_API_KEY).")
        return 1
    if not config.api_url:
        print(
            "Cannot replay: no api_url configured (set PROMPTETHEUS_API_URL or config.toml)."
        )
        return 1
    if not spool_dir.exists():
        print(f"No spool directory at {spool_dir} — nothing to replay.")
        return 0

    before, _ = _scan_spool(spool_dir)
    if before["events"] == 0:
        print("No pending spool events to replay.")
        return 0

    from .transport import DurableHTTPTransport

    transport = DurableHTTPTransport(
        config.api_url, api_key=config.api_key, spool_dir=str(spool_dir)
    )
    try:
        transport.flush()  # drains the (empty) queue and replays pending spool files
    finally:
        transport.close()

    after, _ = _scan_spool(spool_dir)
    replayed = before["events"] - after["events"]
    print(
        f"Replayed {replayed} event(s) to {config.api_url}; {after['events']} still pending."
    )
    return 0 if after["events"] == 0 else 1


def _dead_letter_dir(spool_dir: Path) -> Path:
    return spool_dir / _DEAD_LETTER_DIR


def _spool_purge(spool_dir: Path, *, include_dead_letter: bool) -> int:
    if not spool_dir.exists():
        print(f"No spool directory at {spool_dir} — nothing to purge.")
        return 0
    removed = 0
    for path in spool_dir.glob("*.jsonl"):
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            print(f"  could not remove {path.name}: {exc}")
    if include_dead_letter:
        dead_dir = _dead_letter_dir(spool_dir)
        if dead_dir.exists():
            for path in dead_dir.glob("*.jsonl"):
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    print(f"  could not remove dead-letter/{path.name}: {exc}")
    scope = "spool + dead-letter" if include_dead_letter else "pending spool"
    print(f"Purged {removed} {scope} file(s) from {spool_dir}.")
    return 0


# -- sessions / export / replay / import ------------------------------------


def _cmd_sessions(spool_dir: Path) -> int:
    if not spool_dir.exists():
        print(f"No spool directory at {spool_dir} — no sessions.")
        return 0
    found = 0
    for path in sorted(spool_dir.glob("*.jsonl")):
        events = _read_jsonl(path)
        session_id = path.name[: -len(".jsonl")]
        print(f"  {session_id}: {len(events)} event(s)")
        found += 1
    if found == 0:
        print(f"No sessions found in {spool_dir}.")
    return 0


def _cmd_export(session_id: str, spool_dir: Path, out: str | None) -> int:
    path = _session_file(spool_dir, session_id)
    if path is None:
        print(f"No spooled session {session_id} in {spool_dir}.")
        return 1
    events = _read_jsonl(path)
    types: dict[str, int] = {}
    for event in events:
        types[str(event.get("type"))] = types.get(str(event.get("type")), 0) + 1
    document = {
        "session_id": session_id,
        "events": events,
        "summary": {"count": len(events), "types": types},
    }
    text = json.dumps(document, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"Exported {len(events)} event(s) to {out}.")
    else:
        print(text)
    return 0


def _cmd_replay(target: str, spool_dir: Path, *, tree: bool = False) -> int:
    events = _load_events_for_replay(target, spool_dir)
    if events is None:
        print(f"Could not find a session or file for {target!r}.")
        return 1
    events = sorted(events, key=lambda e: e.get("seq", 0) if isinstance(e, dict) else 0)
    if not events:
        print("(no events)")
        return 0
    if tree:
        from .trace_tree import build_trace_forest, render_tree

        print(render_tree(build_trace_forest(events)))
        return 0
    # Track span nesting for indentation: span_start increases depth, span_end decreases.
    depth = 0
    for event in events:
        etype = event.get("type", "?")
        payload = event.get("payload") or {}
        name = payload.get("name")
        if etype == "state_change" and name == "span_end":
            depth = max(0, depth - 1)
        indent = "  " * depth
        seq = event.get("seq", "?")
        print(f"{indent}[{seq}] {etype}{_replay_detail(etype, payload)}")
        if etype == "state_change" and name == "span_start":
            depth += 1
    return 0


def _cmd_diff(target_a: str, target_b: str, spool_dir: Path) -> int:
    events_a = _load_events_for_replay(target_a, spool_dir)
    events_b = _load_events_for_replay(target_b, spool_dir)
    if events_a is None or events_b is None:
        missing = target_a if events_a is None else target_b
        print(f"Could not find a session or file for {missing!r}.")
        return 1

    from .regression import diff_sessions

    diff = diff_sessions(events_a, events_b)
    summary = diff.summary()
    if not summary:
        print("No differences: the two sessions match.")
        return 0
    print(summary)
    print()
    print("REGRESSED" if diff.regressed else "changed, no regression")
    # A regression is a meaningful non-zero exit so this is usable as a gate.
    return 2 if diff.regressed else 0


def _cmd_fingerprint(target: str, spool_dir: Path) -> int:
    events = _load_events_for_replay(target, spool_dir)
    if events is None:
        print(f"Could not find a session or file for {target!r}.")
        return 1

    from .fingerprint import failure_fingerprint

    fp = failure_fingerprint(events)
    if not fp.is_failure:
        print("No failure detected in this session.")
        return 0
    print(f"{fp.fingerprint}  {fp.label}")
    for signal in fp.signals:
        print(f"  - {signal}")
    return 0


def _cmd_import(file: Path) -> int:
    from .config import load_config

    if not file.exists():
        print(f"No such file: {file}")
        return 1
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        print(f"Could not parse {file} as JSON.")
        return 1
    events = document.get("events") if isinstance(document, dict) else None
    if not isinstance(events, list) or not events:
        print(f"{file} has no events to import.")
        return 0

    config = load_config()
    if not config.api_key:
        print("Cannot import: no api_key configured (set PROMPTETHEUS_API_KEY).")
        return 1
    if not config.api_url:
        print(
            "Cannot import: no api_url configured (set PROMPTETHEUS_API_URL or config.toml)."
        )
        return 1

    from .transport import DurableHTTPTransport

    transport = DurableHTTPTransport(config.api_url, api_key=config.api_key)
    try:
        transport.send_batch(events)
        transport.flush()
    finally:
        transport.close()
    print(f"Imported {len(events)} event(s) to {config.api_url}.")
    return 0


def _replay_detail(etype: str, payload: dict[str, Any]) -> str:
    """A short human detail string for one event in a replay timeline."""
    keys = {
        "agent_message": ("content",),
        "user_message": ("content",),
        "tool_call": ("tool_name",),
        "tool_result": ("call_id",),
        "llm_call": ("model",),
        "browser_action": ("action", "target"),
        "goal_check": ("passed",),
        "state_change": ("name",),
        "score": ("name", "value"),
        "metric": ("name", "value"),
        "error": ("message",),
        "session_end": ("status",),
    }.get(etype, ())
    parts = [f"{k}={payload[k]!r}" for k in keys if k in payload]
    return (" " + " ".join(parts)) if parts else ""


def _session_file(spool_dir: Path, session_id: str) -> Path | None:
    if not spool_dir.exists():
        return None
    direct = spool_dir / f"{session_id}.jsonl"
    if direct.exists():
        return direct
    for path in spool_dir.glob("*.jsonl"):
        if path.name[: -len(".jsonl")] == session_id:
            return path
    return None


def _load_events_for_replay(
    target: str, spool_dir: Path
) -> list[dict[str, Any]] | None:
    """Resolve a replay target to its events: a session id, a .jsonl, or a .json export."""
    path = Path(target)
    if path.is_file():
        if path.suffix == ".json":
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
            events = document.get("events") if isinstance(document, dict) else document
            return events if isinstance(events, list) else None
        return _read_jsonl(path)
    session = _session_file(spool_dir, target)
    return _read_jsonl(session) if session is not None else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    except OSError:
        return []
    return events


# -- helpers ----------------------------------------------------------------


def _scan_spool(spool_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (pending, dead) summaries: {files, events, bytes, per_session}.

    Tolerant of an absent directory and unreadable/partial files; never raises.
    """

    pending: dict[str, Any] = {"files": 0, "events": 0, "bytes": 0, "per_session": {}}
    dead: dict[str, Any] = {"files": 0, "events": 0, "bytes": 0, "per_session": {}}
    if not spool_dir.exists():
        return pending, dead

    for path in sorted(spool_dir.glob("*.jsonl")):
        try:
            size = path.stat().st_size
            lines = sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except OSError:
            continue
        pending["files"] += 1
        pending["events"] += lines
        pending["bytes"] += size
        pending["per_session"][path.name] = lines

    dead_dir = _dead_letter_dir(spool_dir)
    if dead_dir.exists():
        for path in sorted(dead_dir.glob("*.jsonl")):
            try:
                size = path.stat().st_size
                lines = sum(
                    1
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            except OSError:
                continue
            dead["files"] += 1
            dead["events"] += lines
            dead["bytes"] += size
            dead["per_session"][path.name] = lines
    return pending, dead


def _check_health(api_url: str, *, timeout: float = 3.0) -> tuple[bool, str]:
    """Best-effort GET of <api_url>/health. Never raises."""

    from urllib.error import URLError
    from urllib.request import urlopen

    url = api_url.rstrip("/") + "/health"
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint
            status = getattr(response, "status", None) or response.getcode()
            return (200 <= int(status) < 300, f"HTTP {status} from {url}")
    except URLError as exc:
        return (False, f"{exc.reason} ({url})")
    except Exception as exc:  # pragma: no cover - defensive
        return (False, f"{exc} ({url})")


if __name__ == "__main__":
    raise SystemExit(main())
