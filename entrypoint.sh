#!/usr/bin/env bash
set -e

# ── Write Bob Shell global MCP config ─────────────────────────────────────────
# Bob Shell reads ~/.bob/settings/mcp.json for global MCP server definitions.
# We write it at startup so it is always present for every bob run invocation.

mkdir -p "${HOME}/.bob/settings"

cat > "${HOME}/.bob/settings/mcp.json" <<'EOF'
{
  "mcpServers": {
    "fetch": {
      "command": "fetch-mcp",
      "args": [],
      "alwaysAllow": ["fetch"],
      "disabled": false
    }
  }
}
EOF

echo "[entrypoint] MCP config written — fetch tool available to Bob"

# ── Start the Python server ────────────────────────────────────────────────────
exec python3 /app/server.py
