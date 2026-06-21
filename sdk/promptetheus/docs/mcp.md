# Promptetheus MCP

Promptetheus MCP exposes hosted incident and trace evidence to coding agents. The
hosted server is pull-based: the client connects to Promptetheus, then tools read
evidence for the configured Promptetheus project on demand.

## Install Config

Generate a client-specific config snippet:

```bash
promptetheus mcp install \
  --client codex \
  --workspace acme \
  --project-ref abcdefghijklmnopqrst
```

Supported clients are `codex`, `claude`, and `cursor`.

The command prints:

- the hosted MCP URL for the workspace/project pair
- a stdio bridge config using `npx -y mcp-remote <url>`
- the Promptetheus access scope for the server

It does not write global client config files. Paste the printed snippet into the
client or workspace-local config you choose to manage.

## Project Scope

The hosted MCP server should use read-only, project-scoped access by
default. A generated URL includes the Promptetheus workspace and
`project_ref`, so evidence reads are scoped to that project. The SDK and MCP
client config must not receive database service-role keys.

## Local Stdio Server

The existing local command is unchanged:

```bash
promptetheus mcp
```

That path boots the local stdio MCP server when the optional `promptetheus[mcp]`
dependencies and server implementation are available.
