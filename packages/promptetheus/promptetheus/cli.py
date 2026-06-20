"""Service CLI entry point for Promptetheus."""

from __future__ import annotations

import argparse

DEV_HOST = "0.0.0.0"
DEV_PORT = 4318


def _run_dev() -> None:
    """Boot the FastAPI ingestion gateway on :4318."""

    try:
        import uvicorn
    except ImportError:
        print("promptetheus dev needs uvicorn to boot the FastAPI ingestion gateway.")
        print("Install the server dependencies, e.g. pip install 'promptetheus[server]'.")
        return

    try:
        from .server.app import create_app
    except Exception as exc:  # pragma: no cover - defensive CLI behavior
        print("promptetheus dev could not import the FastAPI server app.")
        print(f"Reason: {exc}")
        print("Install the server dependencies, e.g. pip install 'promptetheus[server]'.")
        return

    app = create_app()
    print(f"Starting Promptetheus ingestion gateway on http://{DEV_HOST}:{DEV_PORT}")
    uvicorn.run(app, host=DEV_HOST, port=DEV_PORT)


def _run_mcp() -> None:
    """Boot the incident-context MCP server over stdio."""

    try:
        from .server.mcp import run as run_mcp
    except Exception as exc:  # pragma: no cover - defensive CLI behavior
        print("promptetheus mcp could not import the MCP server module.")
        print(f"Reason: {exc}")
        print("Install the MCP dependencies, e.g. pip install 'promptetheus[mcp]'.")
        return

    try:
        run_mcp()
    except RuntimeError as exc:
        print(str(exc))


def _doctor() -> int:
    try:
        from .server.app import create_app

        create_app()
    except Exception as exc:
        print("Service import: FAILED")
        print(f"Reason: {exc}")
        return 1

    print("Service import: OK")
    print(f"Default dev URL: http://{DEV_HOST}:{DEV_PORT}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="promptetheus")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("dev", help="Boot the local FastAPI ingestion gateway")
    subparsers.add_parser("mcp", help="Boot the incident-context MCP server over stdio")
    subparsers.add_parser("version", help="Print the installed Promptetheus version")
    subparsers.add_parser("doctor", help="Check service imports")

    args = parser.parse_args(argv)

    if args.command == "version":
        from . import __version__

        print(__version__)
        return 0
    if args.command == "dev":
        _run_dev()
        return 0
    if args.command == "mcp":
        _run_mcp()
        return 0
    if args.command == "doctor":
        return _doctor()

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
