#!/usr/bin/env bash
# Start the MCP server (127.0.0.1 only) and the public API in one container.
# If either process stops, the container exits so the platform restarts it.
set -euo pipefail

elkollen-mcp &

# Wait up to 30 s for the MCP server before taking traffic.
for _ in $(seq 1 30); do
  if python -c "import socket; socket.create_connection(('127.0.0.1', ${ELKOLLEN_MCP_PORT:-8001}), 1)" 2>/dev/null; then
    break
  fi
  sleep 1
done

# Trust the platform's proxy headers. Passed as an environment variable: a literal *
# argument gets expanded into file names by some launchers (seen on Windows).
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
uvicorn elkollen_api.app:create_app --factory \
  --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers &

wait -n
echo "a backend process stopped; exiting so the platform restarts the container" >&2
exit 1
