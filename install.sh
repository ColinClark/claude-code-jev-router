#!/usr/bin/env bash
# Install the smart router globally for Claude Code (all projects).
#
#   ./install.sh                     install or update
#   ./install.sh --set-model         also make claude-opus-5-5 the default main-session model
#
# What it does (idempotent):
#   1. Copies this repo to $CLAUDE_ROUTER_HOME (default ~/.claude/router) and builds its venv with uv.
#   2. Ensures Jev credentials exist in ~/.config/jev/.env (prompts if missing, never echoes the key).
#   3. Installs the lane subagents into ~/.claude/agents (never overwrites agents it did not install).
#   4. Imports the orchestration policy from ~/.claude/CLAUDE.md.
#   5. Registers a SessionStart hook in ~/.claude/settings.json that reports router on/off.
#   6. Registers the `jev` stdio MCP server at user scope (`claude mcp add -s user`).
#   7. Verifies the MCP server starts and lists its tools.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST="${CLAUDE_ROUTER_HOME:-$CLAUDE_DIR/router}"
JEV_ENV="${JEV_ENV_FILE:-$HOME/.config/jev/.env}"
SET_MODEL=0
for arg in "$@"; do
  case "$arg" in
    --set-model) SET_MODEL=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

for cmd in uv claude git rsync python3; do
  command -v "$cmd" >/dev/null || die "'$cmd' is required but not on PATH"
done

# 1. Copy and build ---------------------------------------------------------
say "Installing router files to $DEST"
mkdir -p "$DEST"
if [[ "$SRC" != "$DEST" ]]; then
  rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '.claude' \
    --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
    "$SRC/" "$DEST/"
fi
chmod +x "$DEST/hooks/session-start.sh" "$DEST/bin/router-evidence"
# Agents and policy reference the default install path; point them at the real one.
if [[ "$DEST" != "$HOME/.claude/router" ]]; then
  for f in "$DEST"/agents/*.md "$DEST/policy/orchestration.md"; do
    DEST="$DEST" python3 -c 'import os,sys; p=sys.argv[1]; t=open(p).read(); open(p,"w").write(t.replace("~/.claude/router", os.environ["DEST"]))' "$f"
  done
fi
say "Building the jev MCP server environment"
(cd "$DEST/jev-mcp" && uv sync --locked --no-dev --quiet)

# 2. Credentials --------------------------------------------------------------
if [[ -z "${TYPESAFE_API_KEY:-}" ]] && ! grep -q '^TYPESAFE_API_KEY=.' "$JEV_ENV" 2>/dev/null; then
  if [[ -t 0 ]]; then
    printf 'Jev (TypeSafe) API key (input hidden, empty to skip): '
    read -rs key; echo
    if [[ -n "$key" ]]; then
      mkdir -p "$(dirname "$JEV_ENV")"
      (umask 077 && printf 'TYPESAFE_API_KEY=%s\n' "$key" > "$JEV_ENV")
      unset key
      say "Saved credentials to $JEV_ENV (mode 600)"
    else
      warn "No Jev key configured; jev tools will return JEV_UNAVAILABLE until $JEV_ENV exists"
    fi
  else
    warn "No Jev key found; create $JEV_ENV with TYPESAFE_API_KEY=... (chmod 600)"
  fi
else
  if [[ -f "$JEV_ENV" ]]; then chmod 600 "$JEV_ENV"; fi
  say "Jev credentials found"
fi

# 3. Agents -----------------------------------------------------------------
say "Installing lane agents into $CLAUDE_DIR/agents"
mkdir -p "$CLAUDE_DIR/agents"
MANIFEST="$DEST/.installed-agents"
touch "$MANIFEST"
new_manifest="$(mktemp)"
for f in "$DEST"/agents/*.md; do
  name="$(basename "$f")"
  target="$CLAUDE_DIR/agents/$name"
  if [[ -e "$target" ]] && ! grep -qxF "$name" "$MANIFEST" && ! cmp -s "$f" "$target"; then
    warn "skipping $name: $target exists and was not installed by the router"
    continue
  fi
  cp "$f" "$target"
  echo "$name" >> "$new_manifest"
done
# Remove agents a previous version installed but this version no longer ships.
while read -r old; do
  if [[ -n "$old" && ! -f "$DEST/agents/$old" ]]; then rm -f "$CLAUDE_DIR/agents/$old"; fi
done < "$MANIFEST"
mv "$new_manifest" "$MANIFEST"

# 4 + 5. CLAUDE.md import and SessionStart hook --------------------------------
say "Wiring policy import and SessionStart hook"
DEST="$DEST" CLAUDE_DIR="$CLAUDE_DIR" SET_MODEL="$SET_MODEL" python3 - <<'PY'
import json, os, re, shutil, time
from pathlib import Path

dest, claude = Path(os.environ["DEST"]), Path(os.environ["CLAUDE_DIR"])

md = claude / "CLAUDE.md"
block = f"<!-- claude-code-jev-router:begin -->\n@{dest}/policy/orchestration.md\n<!-- claude-code-jev-router:end -->"
text = md.read_text() if md.exists() else ""
pattern = re.compile(r"<!-- claude-code-jev-router:begin -->.*?<!-- claude-code-jev-router:end -->", re.S)
text = pattern.sub(block, text) if pattern.search(text) else (text.rstrip() + "\n\n" + block + "\n").lstrip()
md.write_text(text)

settings_path = claude / "settings.json"
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
if settings_path.exists():
    shutil.copy2(settings_path, settings_path.with_suffix(f".json.bak-router-{int(time.time())}"))
hook_cmd = str(dest / "hooks" / "session-start.sh")
groups = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
groups[:] = [g for g in groups if not any("session-start.sh" in h.get("command", "") and "router" in h.get("command", "")
                                          for h in g.get("hooks", []))]
groups.append({"hooks": [{"type": "command", "command": hook_cmd}]})
if os.environ.get("SET_MODEL") == "1":
    settings["model"] = "claude-opus-5-5"
settings_path.write_text(json.dumps(settings, indent=2) + "\n")
PY

# 6. MCP server -----------------------------------------------------------------
say "Registering the jev stdio MCP server (user scope)"
claude mcp remove jev -s user >/dev/null 2>&1 || true
claude mcp add -s user jev -- "$DEST/jev-mcp/.venv/bin/jev-router-mcp" >/dev/null

# 7. Verify ---------------------------------------------------------------------
say "Verifying the MCP server"
(cd "$DEST/jev-mcp" && uv run --no-dev --quiet python - <<'PY'
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=".venv/bin/jev-router-mcp", args=[])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        policy = (await s.call_tool("get_policy", {})).content[0].text
        print("   tools:", ", ".join(tools))
        print("   policy:", policy[:80] + "...")

asyncio.run(asyncio.wait_for(main(), 30))
PY
) || die "MCP server failed to start; see output above"

say "Done. The router is active in every project."
echo "   Opt out per project:  touch <project>/.claude/router.off"
echo "   Opt out per shell:    export CLAUDE_ROUTER=off"
echo "   Override a lane:      add <project>/.claude/agents/<agent-name>.md"
echo "   Uninstall:            $DEST/uninstall.sh"
