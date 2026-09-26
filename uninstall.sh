#!/usr/bin/env bash
# Remove the smart router from Claude Code.
#   ./uninstall.sh                  remove agents, skills, policy import, hook, MCP server, decision log
#                                   and installed files
#   ./uninstall.sh --purge-credentials   also delete ~/.config/jev/.env
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST="${CLAUDE_ROUTER_HOME:-$CLAUDE_DIR/router}"
JEV_ENV="${JEV_ENV_FILE:-$HOME/.config/jev/.env}"
PURGE=0
[[ "${1:-}" == "--purge-credentials" ]] && PURGE=1

claude mcp remove jev -s user >/dev/null 2>&1 || true

if [[ -f "$DEST/.installed-agents" ]]; then
  while read -r name; do
    if [[ -n "$name" ]]; then rm -f "$CLAUDE_DIR/agents/$name"; fi
  done < "$DEST/.installed-agents"
fi
if [[ -f "$DEST/.installed-skills" ]]; then
  while read -r name; do
    if [[ -n "$name" ]]; then rm -rf "${CLAUDE_DIR:?}/skills/$name"; fi
  done < "$DEST/.installed-skills"
fi
# The router's own decision log (Claude Code transcripts are not touched).
LEDGER="${ROUTER_LEDGER:-$HOME/.local/state/claude-router/decisions.jsonl}"
rm -f "$LEDGER" "$LEDGER.tmp"
rmdir "$HOME/.local/state/claude-router" 2>/dev/null || true

CLAUDE_DIR="$CLAUDE_DIR" python3 - <<'PY'
import json, os, re
from pathlib import Path

claude = Path(os.environ["CLAUDE_DIR"])
md = claude / "CLAUDE.md"
if md.exists():
    text = re.sub(r"\n*<!-- claude-code-jev-router:begin -->.*?<!-- claude-code-jev-router:end -->\n?", "\n",
                  md.read_text(), flags=re.S)
    md.write_text(text.strip() + "\n" if text.strip() else "")

sp = claude / "settings.json"
if sp.exists():
    s = json.loads(sp.read_text())
    groups = s.get("hooks", {}).get("SessionStart", [])
    groups[:] = [g for g in groups if not any("session-start.sh" in h.get("command", "") and "router" in h.get("command", "")
                                              for h in g.get("hooks", []))]
    if not groups:
        s.get("hooks", {}).pop("SessionStart", None)
    if s.get("hooks") == {}:
        s.pop("hooks")
    sp.write_text(json.dumps(s, indent=2) + "\n")
PY

# Only delete a directory that is recognizably a router install.
if [[ -f "$DEST/.installed-agents" && -f "$DEST/policy/orchestration.md" ]]; then
  rm -rf "$DEST"
else
  echo "Left $DEST in place (not a recognizable router install)"
fi
if [[ $PURGE == 1 ]]; then rm -f "$JEV_ENV"; fi
echo "Smart router removed."
