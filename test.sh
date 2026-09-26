#!/usr/bin/env bash
# Run the router's test layers.
#   ./test.sh            ruff lint + format check, unit tests, live Jev smoke test (skipped without credentials)
#   ./test.sh --offline  skip the live Jev smoke test
set -euo pipefail
cd "$(dirname "$0")/jev-mcp"

echo "==> ruff"
uv run ruff check .
uv run ruff format --check .
uv run ruff check --config ../benchmarks/ruff.toml ../benchmarks
uv run ruff format --check --config ../benchmarks/ruff.toml ../benchmarks

echo "==> unit tests"
uv run pytest -q

if [[ "${1:-}" == "--offline" ]]; then
  echo "==> live smoke test skipped (--offline)"
elif [[ -z "${TYPESAFE_API_KEY:-}" ]] && ! grep -q '^TYPESAFE_API_KEY=.' "$HOME/.config/jev/.env" 2>/dev/null; then
  echo "==> live smoke test skipped (no Jev credentials in ~/.config/jev/.env)"
else
  echo "==> live smoke test (stdio MCP -> Jev API)"
  uv run python scripts/smoke_live.py "$PWD/.venv/bin/jev-router-mcp"
fi
