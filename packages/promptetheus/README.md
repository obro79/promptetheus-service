# promptetheus service package

FastAPI service package for Promptetheus trace ingestion, failure analysis,
replay artifacts, fix handoff, GitHub PR integration, MCP tools, and regression
fallbacks.

```bash
python -m pip install -e "packages/promptetheus[server,mcp]"
promptetheus dev
```

The SDK, adapters, transport spool, and exporter integrations are intentionally
not part of this service repository.
