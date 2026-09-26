#!/usr/bin/env bash
# SessionStart hook: tells Claude whether the smart router applies to this session.
# Opt out per project with a `.claude/router.off` file, or per shell with CLAUDE_ROUTER=off.
set -u

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
router_home="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${CLAUDE_ROUTER:-on}" == "off" || -f "$project_dir/.claude/router.off" ]]; then
  echo "Smart router: DISABLED for this session. Ignore the 'Engineering orchestration' policy and work directly."
  exit 0
fi

version="$(sed -n 's/.*"policy_version": *"\([^"]*\)".*/\1/p' "$router_home/policy/policy.json" | head -n1)"
echo "Smart router: ACTIVE (policy ${version:-unknown}). Follow the 'Engineering orchestration' policy for code changes."
echo "Opt out: create .claude/router.off in the project, set CLAUDE_ROUTER=off, or say 'no router' for a task."

if [[ ! -r "$HOME/.config/jev/.env" && -z "${TYPESAFE_API_KEY:-}" ]]; then
  echo "Warning: Jev credentials not found (~/.config/jev/.env); jev tools will return JEV_UNAVAILABLE. Use local routing rules."
fi
exit 0
