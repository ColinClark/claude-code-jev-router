# claude-code-jev-router

A global smart router for [Claude Code](https://code.claude.com). It sends each bounded engineering task to
the **cheapest model and effort level that can do it reliably**. It escalates to stronger models only on
evidence, and it **never reports a task complete while a check is failing**.

- **Claude** does the engineering. The main session orchestrates, and subagents implement.
- **[Jev](https://docs.typesafe.ai)** (TypeSafe System One) makes fast, structured judgment calls such as
  "how hard is this?" and "should we escalate?".
- **Deterministic tools** establish the facts: tests, diffs and workspace fingerprints.

Once installed, it applies to **every project** on your machine unless you turn it off
([see below](#turning-it-off)).

---

## Contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Verifying the install](#verifying-the-install)
- [Using it day to day](#using-it-day-to-day)
- [Turning it off](#turning-it-off)
- [Customizing](#customizing)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Testing and development](#testing-and-development)
- [Troubleshooting](#troubleshooting)
- [Reference](#reference)
- [Design notes](#design-notes)

---

## How it works

```
your request
    │
    ▼
orchestrator (your main Claude session)
    │  writes acceptance criteria, allowed paths and check commands, then records a baseline
    │
    ├──► lane subagent (by exact name) ──► implements one bounded unit, returns evidence
    │       implement-small · implement-medium · implement-high · implement-escalated · implement-extreme
    │
    ├──► lookup / research ──► read-only search and investigation (cheap models)
    │
    ├──► router-evidence ──► runs checks, inspects the diff, checks scope, fingerprints the workspace
    │
    └──► jev MCP tools ──► advisory decisions: classify · progress · escalation · completion
                           (hard gates are enforced locally; Jev can veto but never waive a failure)
    │
    ▼
next unit, retry, escalate, verify, or a final report with lanes used, checks, exit codes and fingerprint
```

### Lanes

| Lane | Agent | Model / effort | Used for |
| --- | --- | --- | --- |
| `OPUS_LOW` | `implement-small` | Opus 5.5 / low | Small, well-understood changes |
| `OPUS_MEDIUM` | `implement-medium` | Opus 5.5 / medium | Normal feature work |
| `OPUS_HIGH` | `implement-high` | Opus 5.5 / high | Complex debugging, cross-cutting or security-sensitive work |
| `FABLE_HIGH` | `implement-escalated` | Fable 5.1 / high | Unresolved architecture or difficult failures |
| `FABLE_XHIGH` | `implement-extreme` | Fable 5.1 / xhigh | Exceptional work, only after an explicit escalation |
| `LOOKUP` | `lookup` | Haiku 4.5 | Read-only symbol and file lookup |
| `RESEARCH` | `research` | Sonnet 5 / medium | Read-only multi-file investigation |

Escalation follows the ladder `OPUS_LOW → OPUS_MEDIUM → OPUS_HIGH → FABLE_HIGH → FABLE_XHIGH` and needs
evidence at each step. Default limits: 2 failed cycles per lane, 6 cycles per unit, and a Jev confidence
threshold of 0.80. When the hard part is solved, the next unit is classified afresh and can drop back to a
cheaper lane.

**What doesn't get routed:** questions, explanations, planning, reviews, and trivial one-file edits. The
main session handles these directly, so they cost no subagent overhead.

---

## Prerequisites

| Tool | Why | Check |
| --- | --- | --- |
| Claude Code | The host; `claude` must be on your `PATH` | `claude --version` |
| [uv](https://docs.astral.sh/uv/) | Builds the MCP server's Python environment | `uv --version` |
| Python 3.14 | Runtime for the MCP server (uv can fetch it: `uv python install 3.14`) | `uv python find 3.14` |
| git, rsync, python3 | Used by the installer and evidence collector | `git --version` |
| jq | Only for `verify-lanes.sh` | `jq --version` |
| A Jev (TypeSafe) API key | For Jev decisions; the router still works without one using local rules only | [typesafe.ai](https://typesafe.ai) |
| Model access | Your Claude account needs Opus 5.5, Fable 5.1, Sonnet 5 and Haiku 4.5 | see [Troubleshooting](#a-lane-fails-with-a-model-access-error) |

---

## Installation

### 1. Get the code

```bash
git clone https://github.com/ColinClark/claude-code-jev-router.git
cd claude-code-jev-router
```

### 2. Run the installer

```bash
./install.sh
```

If a Jev key isn't configured yet, the installer asks for it with hidden input. It saves the key to
`~/.config/jev/.env` with mode `600`. You can also create that file yourself beforehand:

```bash
mkdir -p ~/.config/jev
printf 'TYPESAFE_API_KEY=%s\n' 'your-key-here' > ~/.config/jev/.env
chmod 600 ~/.config/jev/.env
```

Optional flag:

| Flag | Effect |
| --- | --- |
| `--set-model` | Also sets `claude-opus-5-5` as your default main-session model in `~/.claude/settings.json`, which is the recommended orchestrator |

### 3. What the installer changes

The installer is **idempotent**, so running it again is safe. It makes only these changes:

| # | Change | Location |
| --- | --- | --- |
| 1 | Copies the router and builds its Python venv | `~/.claude/router/` |
| 2 | Makes sure the Jev key file exists (prompts if missing) | `~/.config/jev/.env` |
| 3 | Copies the 7 lane agents. It **never overwrites** an agent file it didn't install; it warns and skips instead | `~/.claude/agents/` |
| 4 | Adds a marked block importing the policy. Your existing content is untouched | `~/.claude/CLAUDE.md` |
| 5 | Adds a `SessionStart` hook, after writing a timestamped backup (`settings.json.bak-router-*`) | `~/.claude/settings.json` |
| 6 | Registers the `jev` **stdio MCP server** at user scope | `claude mcp add -s user jev -- ~/.claude/router/jev-mcp/.venv/bin/jev-router-mcp` |
| 7 | Starts the MCP server once and lists its tools to confirm it works | — |

To install into non-default locations, set these environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude Code config directory to install into |
| `CLAUDE_ROUTER_HOME` | `$CLAUDE_CONFIG_DIR/router` | Where the router files live |
| `JEV_ENV_FILE` | `~/.config/jev/.env` | Where the installer looks for, or writes, the Jev key |

### 4. Start a new session

The policy and hook load at session start. Open a **new** Claude Code session in any project; the router
does not attach to sessions that are already running.

---

## Verifying the install

Inside Claude Code:

| Check | Expect |
| --- | --- |
| `/mcp` | `jev` is listed as connected, with 5 tools |
| `/agents` | `implement-small` … `implement-extreme`, `lookup` and `research` under user agents |
| `/memory` | `~/.claude/CLAUDE.md` imports `~/.claude/router/policy/orchestration.md` |
| Ask: *"Is the smart router active?"* | Claude quotes the `Smart router: ACTIVE (policy 1.0)` line from the SessionStart hook |

From the shell:

```bash
claude mcp get jev                 # the registered command
./verify-lanes.sh                  # proves each agent really runs on its configured model (costs a few cents)
./verify-lanes.sh lookup           # check a single agent
```

`verify-lanes.sh` runs headless Claude sessions in a temporary directory. It reads `modelUsage` from each
result to confirm that the agent ran on the model in `policy.json`. It can't observe effort levels; check
those with `/agents`.

---

## Using it day to day

Work as usual; there's no new command to learn. For any request that changes code beyond a trivial edit,
the main session:

1. **Writes a contract:** acceptance criteria (`A1`, `A2`, …), allowed paths, and the repo's own check
   commands (tests, typecheck, lint, build). It records a baseline, so failures that existed before the
   change stay visible.
2. **Routes the work.** Obvious cases are routed directly. Otherwise it asks `jev.classify_task`, then
   dispatches the smallest useful unit to a lane agent.
3. **Collects evidence itself** with `router-evidence` after every worker cycle, instead of trusting the
   worker's report.
4. **Decides:** continue, retry (only with a new hypothesis), verify, escalate, complete, or blocked.
5. **Reports:** the lanes used and why, the changed files, each check with its exit code, the evidence
   fingerprint, and any limitations.

### Useful phrasings

| You say | Effect |
| --- | --- |
| "no router" / "work directly" | Skip orchestration for this task |
| "use implement-high for this" | Force a lane |
| "security-sensitive" | Floors classification at `OPUS_HIGH` |
| "you may use FABLE_XHIGH" | Allows the top lane; otherwise it's reached only by explicit escalation |
| "budget: 3 cycles" | Tightens the cycle limit for this task |

### Running the evidence collector yourself

```bash
~/.claude/router/bin/router-evidence fingerprint
~/.claude/router/bin/router-evidence collect \
    --check 'tests=npm test' --check 'types=npm run typecheck' \
    --allow 'src/*' --allow 'tests/*'
~/.claude/router/bin/router-evidence verify wsfp-3d2ed63e6d3df718cdc9fee8   # exit 0 only if unchanged
```

`collect` prints a JSON packet containing check statuses and exit codes, the changed files, any
out-of-scope files, and a `stale` flag (set when a check such as a formatter modified the workspace). Full
logs are written to `.git/router-evidence/<fingerprint>/`.

---

## Turning it off

Opting out disables the **orchestration policy**: the SessionStart hook tells Claude to ignore it and work
directly. The lane agents and `jev` tools stay installed but go unused. Opt-outs take effect when a
session starts, so open a new session or run `/clear` after changing one.

### For a single task

Say **"no router"** or **"work directly"** in your request.

### For one project

Create a marker file in the project root (the directory you launch `claude` from):

```bash
mkdir -p .claude && touch .claude/router.off
```

- **Commit it** to turn the router off for everyone who works on the repo.
- **Keep it personal** by adding it to the repo's local exclude list instead of `.gitignore`:
  ```bash
  echo '.claude/router.off' >> .git/info/exclude
  ```

Turn it back on with `rm .claude/router.off`.

The marker is only checked in the launch directory. In a multi-project workspace, put it in whichever
directory you start `claude` from.

### For one shell or terminal session

```bash
export CLAUDE_ROUTER=off
claude
```

Or for a single launch: `CLAUDE_ROUTER=off claude`.

### Everywhere, without uninstalling

Add this to your shell profile (`~/.zshrc`, `~/.bashrc`):

```bash
export CLAUDE_ROUTER=off
```

Remove the line to turn the router back on.

### Precedence

The router is **off** if any of these is true:
- `CLAUDE_ROUTER=off` is set in the environment
- `<launch dir>/.claude/router.off` exists
- you said "no router" for the task

Otherwise it is **on**.

---

## Customizing

### Replace a lane for one project

Project agents take precedence over user agents with the same name. To make `implement-medium` use
different settings in one repo:

```bash
mkdir -p .claude/agents
cp ~/.claude/agents/implement-medium.md .claude/agents/
# edit model:, effort:, tools:, maxTurns: or the instructions
```

### Change the global policy

Edit these files in your clone, then re-run `./install.sh`:

| File | Controls |
| --- | --- |
| `policy/policy.json` | Lane → agent/model/effort mapping, the escalation ladder, class descriptions sent to Jev, the confidence threshold, cycle limits, and the Jev endpoint/model/timeout |
| `agents/*.md` | Each lane's model, effort, tool allowlist, `maxTurns` and worker instructions |
| `policy/orchestration.md` | The orchestrator's rules, imported into `~/.claude/CLAUDE.md` |

If you change a lane's model in `policy.json`, change it in the matching `agents/*.md` too. The agent
file controls what actually runs; `policy.json` is what the `jev` tools report and validate against.

Bump `policy_version` in `policy.json` whenever routing semantics change. The `jev` tools reject
requests that carry an old version.

---

## Updating

```bash
cd claude-code-jev-router
git pull
./install.sh
```

Updating refreshes `~/.claude/router/`, the agents it owns, and the MCP registration. It removes agents
dropped by the new version. Your Jev key and any agents you wrote yourself are left alone.

---

## Uninstalling

```bash
~/.claude/router/uninstall.sh                      # keeps your Jev key
~/.claude/router/uninstall.sh --purge-credentials  # also deletes ~/.config/jev/.env
```

Uninstall removes:
- the `jev` MCP registration
- only the agents the router installed
- the marked import block in `~/.claude/CLAUDE.md`
- the SessionStart hook entry
- `~/.claude/router/`

It leaves the rest of your settings, your own agents, and the `settings.json.bak-router-*` backups in
place.

---

## Testing and development

```bash
./test.sh              # ruff lint + format check, unit tests, live Jev smoke test
./test.sh --offline    # skip the live Jev test (no key or no network)
```

| Layer | Command | What it proves |
| --- | --- | --- |
| Lint | `ruff check` and `ruff format --check` (in `test.sh`) | Code style and common bug patterns (ruff rules E, F, W, I, B, UP, S, SIM, RUF) |
| Unit | `uv run pytest` in `jev-mcp/` | Strict schemas and size limits; hard gates; ladder routing; the rule that failed, unrun or errored checks block COMPLETE; Jev client retries and error mapping; the key never appears in errors; fingerprints change on staged, unstaged and untracked edits |
| Live | `./test.sh` | The stdio MCP server starts; real Jev classifications land in sensible lanes; failing evidence can't COMPLETE; identity and fingerprint are echoed back |
| Installer | `CLAUDE_CONFIG_DIR=/tmp/sb/.claude JEV_ENV_FILE=/tmp/sb/jev.env ./install.sh` | Install, reinstall and uninstall against a scratch config directory, without touching your real one |
| End to end | `./verify-lanes.sh` | Each agent actually runs on its configured model inside Claude Code |

Working on the MCP server:

```bash
cd jev-mcp
uv sync                              # includes dev tools (pytest, ruff)
uv run pytest -q
uv run ruff check --fix . && uv run ruff format .
uv run python scripts/smoke_live.py "$PWD/.venv/bin/jev-router-mcp"
```

---

## Troubleshooting

### `jev` doesn't appear in `/mcp`, or shows as failed
- Run `claude mcp get jev` and check that the command path exists.
- Run the server by hand to see its error: `~/.claude/router/jev-mcp/.venv/bin/jev-router-mcp < /dev/null`.
- Re-run `./install.sh`, which rebuilds the venv and re-registers the server.

### Jev tools return `"error": "JEV_UNAVAILABLE"`
- The key is missing or wrong. Check that `~/.config/jev/.env` contains `TYPESAFE_API_KEY=...` and has
  mode `600`.
- The Jev API is down or rate limited. The client retries once, then gives up.
- The router keeps working in this state: the orchestrator falls back to local routing rules, and
  decisions that need judgment report BLOCKED instead of guessing.

### Jev tools return `"error": "INVALID_REQUEST"`
- The request didn't match the schema: an unknown field, oversized input (16 KiB total, 2,000 characters
  per summary), an unknown lane, or a `policy_version` mismatch after a policy change. The `reason` field
  names the problem.

### Claude doesn't route; it just does the work
- Open a new session. The hook and policy only load at session start.
- Ask *"Is the smart router active?"*. If Claude says DISABLED, look for `CLAUDE_ROUTER=off` in your
  environment or a `.claude/router.off` file.
- Trivial edits and questions are handled directly by design.
- Check `/memory` for the import. If it's missing, re-run `./install.sh`.

### The installer says "skipping research.md: exists and was not installed by the router"
You already have an agent with that name. Rename or remove yours and re-run the installer, or keep yours,
in which case that lane uses your definition.

### A lane fails with a model access error
Your account or organization may not have access to one of the models, or an organization cap may
override the agent's model or effort. Change that lane's `model:` in `agents/<agent>.md` (and in
`policy/policy.json`), re-run `./install.sh`, then confirm with `./verify-lanes.sh`.

### Where are decisions logged?
Decisions are written to `~/.local/state/claude-router/decisions.jsonl`, one line per decision: IDs,
action or class, route, confidence, and who decided. Task text and evidence bodies are not logged. Use the
log to tune thresholds and limits.

---

## Reference

### MCP tools (`mcp__jev__*`)

| Tool | Purpose | Possible outputs |
| --- | --- | --- |
| `get_policy` | Deployed policy version, lanes, ladder and limits | — |
| `classify_task` | Class for a new work unit, plus its route | `SMALL`, `MEDIUM`, `HIGH`, `ESCALATE` |
| `assess_progress` | Next step after a worker cycle | `CONTINUE`, `RETRY`, `VERIFY`, `ESCALATE`, `COMPLETE`\*, `BLOCKED` |
| `decide_escalation` | Lane change, with the new route computed from the ladder | `KEEP`, `ESCALATE`, `DEESCALATE`, `VERIFY`, `BLOCKED` |
| `assess_completion` | Residual acceptance judgment once the hard gates pass | `COMPLETE`\*, `VERIFY`, `CONTINUE` |

\* `COMPLETE` is only possible when every check passes (or is an accepted N/A), at least one check passed,
all criteria are SATISFIED, `scope_ok` is true, there are no known failures, and Jev's confidence is at or
above the threshold.

Every reply echoes `schema_version`, `request_id`, `task_id`, `policy_version` and `evidence_fingerprint`,
and includes `confidence`, `reason` and `decided_by` (`jev` or `local_rule`). A reply with an `error` field
is never a decision.

### Repository layout

```
agents/                 7 lane subagents (model, effort, tool allowlist, worker contract)
policy/orchestration.md orchestrator rules, imported into ~/.claude/CLAUDE.md
policy/policy.json      lanes, ladder, classes, limits, Jev endpoint
hooks/session-start.sh  prints router ACTIVE/DISABLED into each new session
bin/router-evidence     wrapper for the evidence collector
jev-mcp/                Python package (uv, Python 3.14)
  src/jev_router/         server.py (MCP), decisions.py, policy.py, schemas.py, jev.py, evidence.py
  tests/                  pytest suite
  scripts/smoke_live.py   live end-to-end smoke test
install.sh · uninstall.sh · test.sh · verify-lanes.sh
```

### Files outside the repo

| Path | Owner | Contents |
| --- | --- | --- |
| `~/.claude/router/` | installer | Installed copy and venv |
| `~/.claude/agents/<lane>.md` | installer | Lane agents (tracked in `~/.claude/router/.installed-agents`) |
| `~/.claude/CLAUDE.md` | you + installer | Your content, plus the `claude-code-jev-router` import block |
| `~/.claude/settings.json` | you + installer | Your settings, plus one SessionStart hook entry |
| `~/.config/jev/.env` | you | `TYPESAFE_API_KEY`, mode 600 |
| `~/.local/state/claude-router/decisions.jsonl` | MCP server | Sanitized decision log |
| `<repo>/.git/router-evidence/` | evidence collector | Full check logs per fingerprint |

---

## Design notes

- **Routes are computed locally.** Jev only picks a class or action from an allowlisted set. The lane,
  model and effort always come from `policy.json`, so Jev can't produce a route the policy doesn't allow.
- **Hard gates come before Jev.** Failed, unrun or errored checks; unsatisfied or unknown criteria;
  out-of-scope diffs; and known failures are all evaluated locally. Jev is only asked about what's left
  after that.
- **Low-confidence classification** hedges to the stronger of Jev's two top candidates, not blindly one
  class up. Security-sensitive work is floored at HIGH. `FABLE_XHIGH` is never a first classification.
- **Retries require a new hypothesis.** Repeating an unchanged failed attempt uses up budget without adding
  evidence.
- **Credentials:** the MCP server process is the only thing that reads the key, from `TYPESAFE_API_KEY` or
  `~/.config/jev/.env`. The key is never logged or returned. This is a same-user boundary, not strict
  isolation: a worker with Bash could still read the file. For strict isolation, run the server as a
  separate user or service behind an authenticated HTTP transport.
- **Jev client:** calls the documented `POST https://api.typesafe.ai/v1/systemone` endpoint with httpx
  (one retry with jitter on transport errors and 429/5xx, no retry on 401/403). The official `typesafe-sdk`
  package could replace it.
