# claude-code-jev-router

A global smart router for Claude Code. It sends each bounded engineering task to the cheapest model/effort
lane that can do it reliably, escalates only on evidence, and never reports completion while a check is
failing. [Jev](https://docs.typesafe.ai) (TypeSafe System One) supplies the fast, structured judgment calls,
such as "how hard is this?" or "should we escalate?". Deterministic tools supply the facts: tests, diffs and
workspace fingerprints.

After installation it applies to **every project** unless you opt out.

```
request ─► orchestrator (main session: contract, routing, final report)
              │ dispatches by exact agent name
              ├─► implement-small | -medium | -high | -escalated | -extreme   (Opus 5.5 / Fable 5.1)
              ├─► lookup (Haiku 4.5) · research (Sonnet 5)                    read-only
              ├─► router-evidence   checks, diff, scope, workspace fingerprint (deterministic)
              └─► jev MCP           classify · progress · escalation · completion (advisory)
                                    hard gates enforced locally; Jev can veto, never waive
```

## Install

```bash
git clone git@github.com:ColinClark/claude-code-jev-router.git
cd claude-code-jev-router
./install.sh                # add --set-model to make Opus 5.5 the default main-session model
```

Requirements: `uv`, `claude`, `git`, `rsync`, `python3` (the venv uses Python 3.14 via `.python-version`).

The installer is idempotent; re-run it after `git pull` to update. It:

| Step | Where |
| --- | --- |
| Copies the router and builds its venv | `~/.claude/router/` |
| Jev key (prompts if missing, mode 600) | `~/.config/jev/.env` |
| Lane subagents (never overwrites agents it didn't install) | `~/.claude/agents/*.md` |
| Policy import | `~/.claude/CLAUDE.md` → `@~/.claude/router/policy/orchestration.md` |
| SessionStart hook (reports router on/off) | `~/.claude/settings.json` (backup written first) |
| `jev` stdio MCP server, user scope | `claude mcp add -s user jev -- …/jev-router-mcp` |

`CLAUDE_CONFIG_DIR`, `CLAUDE_ROUTER_HOME` and `JEV_ENV_FILE` override the default locations.
Uninstall with `~/.claude/router/uninstall.sh` (add `--purge-credentials` to delete the key file too).

## Overriding

| Scope | How |
| --- | --- |
| One task | Say "no router" or "work directly" |
| One project | `touch <project>/.claude/router.off` |
| One shell | `export CLAUDE_ROUTER=off` |
| One lane in one project | Add `<project>/.claude/agents/implement-medium.md` (project agents win over user agents) |
| Policy (lanes, limits, thresholds) | Edit `policy/policy.json` and re-run `./install.sh` |

## Testing

| Layer | Command | What it proves |
| --- | --- | --- |
| Lint + unit | `./test.sh --offline` | ruff clean; 41 tests: schemas, hard gates, routing ladder, Jev client retries/errors/no key leakage, fingerprints |
| Live Jev | `./test.sh` | stdio MCP server starts, real Jev classifications land in sane lanes, failing evidence can't COMPLETE |
| Installer | `CLAUDE_CONFIG_DIR=/tmp/sandbox/.claude ./install.sh` | install/reinstall/uninstall against a scratch config dir, leaving yours untouched |
| In Claude | `./verify-lanes.sh` | each agent actually runs on its configured model (checked through `modelUsage`) |

Then try it on a real task in any project, e.g. *"add input validation to X with a regression test"*.
The final report should name the lane used, the checks with exit codes, and the evidence fingerprint.
Decisions are logged (without task text) to `~/.local/state/claude-router/decisions.jsonl` for tuning.

## Layout

```
agents/          7 lane subagents (model, effort, tool allowlist)
policy/          orchestration.md (global CLAUDE.md policy), policy.json (lanes, ladder, limits)
hooks/           session-start.sh (router on/off context)
bin/             router-evidence wrapper
jev-mcp/         Python package: MCP server (jev_router.server) + evidence collector + tests
install.sh · uninstall.sh · test.sh · verify-lanes.sh
```

## Design notes and deviations from the spec

- **Routes are computed locally.** Jev only picks a class or action from an allowlisted set; the lane,
  model and effort always come from `policy.json`, so Jev can't produce a disallowed route.
- **Low-confidence classification** hedges to the stronger of Jev's top two candidates instead of blindly
  going one class up. Security-sensitive work is floored at HIGH. The top lane (FABLE_XHIGH) is never a
  first classification.
- **BLOCKED** is returned by `assess_progress` when the unit cycle budget is exhausted, and by
  `decide_escalation` when escalation is warranted but no higher lane is available.
- **Credentials:** the key is read only inside the MCP server process, from `TYPESAFE_API_KEY` or
  `~/.config/jev/.env`, and is never logged or returned. This is a same-user boundary, not isolation:
  a worker with Bash could still read the file. For strict isolation, run the server as a separate user or
  service behind an authenticated HTTP transport, as the spec describes.
- The Jev client calls the documented `POST /v1/systemone` HTTP API directly with httpx. The official
  `typesafe-sdk` (PyPI, 0.7.1) could replace it; it was not added here.
