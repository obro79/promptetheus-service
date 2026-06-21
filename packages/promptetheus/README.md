# promptetheus service package

FastAPI service package for Promptetheus trace ingestion, failure analysis,
replay artifacts, fix handoff, GitHub PR integration, MCP tools, and regression
fallbacks.

```bash
python -m pip install -e "packages/promptetheus[server,mcp]"
promptetheus dev
```

MCP read tools use the same project API key as the SDK:

```bash
export PROMPTETHEUS_API_KEY=pt_live_...
```

Use `PROMPTETHEUS_CONSOLE_TOKEN` only for owner-only console workflows.

The SDK, adapters, transport spool, and exporter integrations are intentionally
not part of this service repository.
