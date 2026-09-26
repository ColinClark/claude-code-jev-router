#!/usr/bin/env bash
# SessionStart hook: tells Claude whether the smart router applies to this session, and its session id
# (routing decisions use it as their task_id prefix so the dispatch gate can match them to this session).
# Opt out per project with a `.claude/router.off` file, or per shell with CLAUDE_ROUTER=off.
set -u

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
router_home="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${CLAUDE_ROUTER:-on}" == "off" || -f "$project_dir/.claude/router.off" ]]; then
  echo "Smart router: DISABLED for this session. Ignore the 'Engineering orchestration' policy and work directly."
  exit 0
fi

session_id="$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id",""))
except Exception: print("")' 2>/dev/null)"
version="$(sed -n 's/.*"policy_version": *"\([^"]*\)".*/\1/p' "$router_home/policy/policy.json" | head -n1)"

echo "Smart router: ACTIVE (policy ${version:-unknown}). Follow the 'Engineering orchestration' policy for code changes."
if [[ -n "$session_id" ]]; then
  echo "Router session id: $session_id — start every jev task_id with \"$session_id:\" (e.g. \"$session_id:unit-1\")."
fi
echo "Opt out: create .claude/router.off in the project, set CLAUDE_ROUTER=off, or say 'no router' for a task."

if [[ ! -r "$HOME/.config/jev/.env" && -z "${TYPESAFE_API_KEY:-}" ]]; then
  echo "Warning: Jev credentials not found (~/.config/jev/.env); jev tools will return JEV_UNAVAILABLE. Use local routing rules."
fi
exit 0
