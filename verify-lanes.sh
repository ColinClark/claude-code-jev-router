#!/usr/bin/env bash
# End-to-end check inside real Claude Code (run after ./install.sh; costs a few cents).
# For each lane, asks a headless session to dispatch that agent with a no-op task, then checks
# `modelUsage` in the result to prove the agent really ran on the configured model.
# Effort cannot be observed this way; confirm it in /agents or the session transcript.
#
#   ./verify-lanes.sh            all lanes
#   ./verify-lanes.sh lookup     one agent
set -uo pipefail

ROUTER_HOME="${CLAUDE_ROUTER_HOME:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/router}"
POLICY="$ROUTER_HOME/policy/policy.json"
[[ -f "$POLICY" ]] || { echo "router not installed ($POLICY missing); run ./install.sh first" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
cd "$workdir" || exit 1

fail=0
while IFS=$'\t' read -r lane agent model; do
  [[ -n "${1:-}" && "$1" != "$agent" ]] && continue
  out="$(claude -p "Use the $agent subagent. Its task: reply with exactly the word OK and do nothing else. Then reply OK yourself." \
          --output-format json --max-turns 4 --allowedTools Agent 2>/dev/null)"
  used="$(jq -r '(.modelUsage // {}) | keys | join(",")' <<<"$out" 2>/dev/null)"
  if [[ ",$used," == *",$model"* ]]; then
    printf 'PASS  %-12s %-20s ran on %s\n' "$lane" "$agent" "$model"
  else
    printf 'FAIL  %-12s %-20s expected %s, models used: %s\n' "$lane" "$agent" "$model" "${used:-none}"
    fail=1
  fi
done < <(jq -r '.lanes | to_entries[] | [.key, .value.agent, .value.model] | @tsv' "$POLICY")

echo "--- jev MCP server"
if claude mcp get jev >/dev/null 2>&1; then echo "PASS  jev MCP server registered"; else echo "FAIL  jev MCP server not registered"; fail=1; fi
exit $fail
