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
- [Benchmark: router vs. no router](#benchmark-router-vs-no-router)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Verifying the install](#verifying-the-install)
- [Using it day to day](#using-it-day-to-day)
- [Usage reporting](#usage-reporting)
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
    │  Step 0: jev.classify_task on the whole task, then picks a mode
    │
    ├── lightweight mode (one unit, route ≤ OPUS_MEDIUM, not security-sensitive, not long-running)
    │       implements it directly, runs the repo's checks at the end;
    │       two failed attempts → full mode with escalation
    │
    └── full mode (multi-part, long-running or security-sensitive work)
            writes acceptance criteria, allowed paths and check commands, records a baseline,
            splits into units and classifies every unit (first attempts capped at OPUS_MEDIUM)
    │
    ├──► dispatch gate (PreToolUse hook) ──► blocks any implement-* dispatch without a routing decision
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
| `OPUS_LOW` | `implement-small` | Opus 5.5 / low | Small, well-understood changes: scaffolding, config, a CLI over existing code |
| `OPUS_MEDIUM` | `implement-medium` | Opus 5.5 / medium | Normal feature work |
| `OPUS_HIGH` | `implement-high` | Opus 5.5 / high | Complex debugging, cross-cutting or security-sensitive work |
| `FABLE_HIGH` | `implement-escalated` | Fable 5.1 / high | Unresolved architecture or difficult failures |
| `FABLE_XHIGH` | `implement-extreme` | Fable 5.1 / xhigh | Exceptional work, only after an explicit escalation |
| `LOOKUP` | `lookup` | Haiku 4.5 | Read-only symbol and file lookup |
| `RESEARCH` | `research` | Sonnet 5 / medium | Read-only multi-file investigation |

Escalation follows the ladder `OPUS_LOW → OPUS_MEDIUM → OPUS_HIGH → FABLE_HIGH → FABLE_XHIGH` and is
**evidence-driven**:
- **Capped first attempts.** A unit's first attempt runs at most on OPUS_MEDIUM, even when Jev predicts
  HIGH or ESCALATE (`first_attempt_max_lane` in `policy.json`). OPUS_HIGH and the Fable lanes are reached
  only through `decide_escalation` after verification has shown a real failure.
- **Security exception.** Security-sensitive units start at OPUS_HIGH.
- **Limits.** 2 failed cycles per lane, 6 cycles per unit, and a Jev confidence threshold of 0.80. Below the
  threshold, a classification hedges *down* to the cheaper of Jev's top two classes.
- **De-escalation.** When the hard part is solved, the next unit is classified afresh and can drop back to
  a cheaper lane.

The [benchmarks](#benchmark-router-vs-no-router) show why: routing on predicted difficulty sent units that
Opus at medium effort solves to Fable, at 2–4× the cost.

**What doesn't get routed:** questions, explanations, planning, reviews, and trivial one-file edits. The
main session handles these directly, so they cost no subagent overhead.

---

## Benchmark: router vs. no router

[`benchmarks/`](benchmarks/) runs the same task headlessly with the router off (`CLAUDE_ROUTER=off`) and
on, from the same seed repo and budget, and grades every result with a hidden acceptance suite that no run
sees. There are four tasks, from a small feature up to a SQL engine graded against SQLite; 67 runs in
total. Final configuration (policy 1.6) against a strong single-model baseline (Opus 5.5, medium effort):

| Task | Hidden acceptance | Opus 5.5 baseline | Router, policy 1.6 | Verdict |
| --- | --- | ---: | ---: | --- |
| tinykv (small feature) | 10/10, all runs | $0.53 · 2.0 min | $0.57 · 1.7 min | parity |
| billing (audit, 6 planted bugs) | 25/25 and 6/6 bugs, all runs | $0.48 · 1.4 min | $0.48 · 1.3 min | parity |
| miniregex (regex engine vs. `re`) | 77/77, all runs | $2.26 · 30 min | $2.02 · 28 min | parity |
| minisql (SQL engine vs. SQLite) | 79/79, all runs | $5.23 · 22 min | **$3.82 · 16 min** | **27% cheaper and faster** |

**What we learned** (the details, and every policy tested, are in [`benchmarks/README.md`](benchmarks/README.md)):
- **Escalate on evidence, not prediction.** Routing "hard-looking" units to Opus high effort or Fable on
  prediction cost 2–4× with no quality gain, because Opus at medium effort solved them. So first attempts
  are capped at OPUS_MEDIUM, and stronger lanes need a verified failure.
- **Size the process to the task.** Full orchestration costs 30–130% extra on small tasks. Lightweight
  mode, which does single-unit tasks directly and runs checks at the end, brings them back to parity.
- **The router rescues cheaper models.** Sonnet 5 alone failed minisql (69/79); a Sonnet orchestrator with
  the router scored 79/79 for less than the Opus baseline. Against "Fable for everything", the router gets
  the same quality for much less.
- **Part of the gain is operating discipline,** not multi-model routing. On these tasks no escalation was
  ever needed.

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
| `--set-model` | Also sets `claude-opus-5-5` as your default main-session model (the orchestrator) in `~/.claude/settings.json`. This is the recommended orchestrator; in the [benchmark](#benchmark-router-vs-no-router), a Sonnet 5 orchestrator was slower and more expensive |
| `--set-model=MODEL` | Sets any other main-session model, for example `--set-model=claude-sonnet-5` |

### 3. What the installer changes

The installer is **idempotent**, so running it again is safe. It makes only these changes:

| # | Change | Location |
| --- | --- | --- |
| 1 | Copies the router and builds its Python venv | `~/.claude/router/` |
| 2 | Makes sure the Jev key file exists (prompts if missing) | `~/.config/jev/.env` |
| 3 | Copies the 7 lane agents. It **never overwrites** an agent file it didn't install; it warns and skips instead | `~/.claude/agents/` |
| 3b | Installs the `/router-report` skill, with the same no-overwrite rule | `~/.claude/skills/router-report/` |
| 4 | Adds a marked block importing the policy. Your existing content is untouched | `~/.claude/CLAUDE.md` |
| 5 | Adds a `SessionStart` hook (router on/off and session id) and a `PreToolUse` [dispatch gate](#the-dispatch-gate) on the Agent tool, after writing a timestamped backup (`settings.json.bak-router-*`) | `~/.claude/settings.json` |
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
| Ask: *"Is the smart router active?"* | Claude quotes the `Smart router: ACTIVE (policy 1.6)` line from the SessionStart hook, along with the router session id |
| `/router-report` | A usage report for the last 24 hours |

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
the main session starts with **Step 0**: it classifies the whole task with Jev and sizes the process to
the result.

**Lightweight mode** covers most everyday tasks: one coherent unit routed at OPUS_MEDIUM or lower, not
security-sensitive, and not long-running. The main session implements the change itself, runs the repo's
checks at the end, and reports. There's no worker dispatch, evidence baseline or per-unit contract. If the
checks still fail after two honest attempts, it switches to full mode and escalates.

**Full mode** is for multi-part, long-running or security-sensitive work. The main session:

1. **Writes a contract:** acceptance criteria (`A1`, `A2`, …), allowed paths, and the repo's own check
   commands (tests, typecheck, lint, build). It records a baseline, so failures that existed before the
   change stay visible.
2. **Splits and routes the work.** It splits the task into the smallest useful units, keeping parts that
   belong in different lanes separate. It calls `jev.classify_task` for **every** unit and dispatches
   exactly the agent in the returned route; first attempts are capped at OPUS_MEDIUM. The
   [dispatch gate](#the-dispatch-gate) enforces this. Each worker runs in a fresh context, which is what
   makes long tasks cheaper than one ever-growing session.
3. **Waits for every worker** and collects evidence itself with `router-evidence` after each cycle, instead
   of trusting the worker's report.
4. **Decides:** continue, retry (only with a new hypothesis), verify, escalate (only after a verified
   failure), complete, or blocked.
5. **Reports:** the lanes used and why, the changed files, each check with its exit code, the evidence
   fingerprint, and any limitations.

### Useful phrasings

| You say | Effect |
| --- | --- |
| "no router" / "work directly" | Skip orchestration for this task |
| "use implement-high for this" | Force a lane. Recorded with `record_override`, so the gate allows it and the report shows it |
| "security-sensitive" | Floors classification at `OPUS_HIGH` |
| "you may use FABLE_XHIGH" | Allows the top lane; otherwise it's reached only by explicit escalation |
| "budget: 3 cycles" | Tightens the cycle limit for this task |

### The dispatch gate

Prompt instructions alone don't guarantee routing. In an early test the orchestrator skipped Jev,
judging the class "obvious", and routed the work on its own judgment. So a `PreToolUse` hook
(`router-gate`) runs before every Agent tool call. It only governs *dispatches*: lightweight mode, where
the main session does the work itself, involves none.

- **Gated agents:** a dispatch to an implementation lane (`implement-small` … `implement-extreme`) is
  allowed only if this session has an unused routing decision in the decision log that names that agent.
  That can be `classify_task`, `decide_escalation` (ESCALATE, DEESCALATE or KEEP), or `record_override`.
- **One per dispatch:** each decision allows one dispatch.
- **Session-scoped:** the SessionStart hook prints the session id, and decisions use
  `"<session id>:<unit>"` as their `task_id`.
- **When blocked,** Claude sees the steps to follow: load the jev tools with ToolSearch, call
  `classify_task`, then dispatch the agent in the returned route.
- **Never gated:** `lookup`, `research`, other agents such as Explore or general-purpose, and anything
  when the router is off.
- **Degraded mode:** if Jev returns `JEV_UNAVAILABLE`, the gate allows dispatches for 15 minutes, so an
  outage falls back to local routing rules instead of blocking work.
- **Logged:** every allow, block and degraded pass goes to the decision log, and `/router-report` shows
  the counts.

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
logs are written to `.git/router-evidence/<fingerprint>/`. Log folders older than the retention window
(24 hours by default) are deleted on the next `collect`.

---

## Usage reporting

See which models, lanes and effort levels your work actually ran on, with token counts and an estimated
cost. Run it inside Claude Code:

```
/router-report                     # last 24 hours
/router-report --hours 6           # a different window
/router-report --project msft      # only projects whose path contains "msft"
```

Or from the shell:

```bash
~/.claude/router/bin/router-report                      # text tables, last 24 hours
~/.claude/router/bin/router-report --hours 168          # the last week
~/.claude/router/bin/router-report --format markdown    # the format /router-report shows
~/.claude/router/bin/router-report --format json        # for scripts and dashboards
~/.claude/router/bin/router-report --top 20             # list more projects (default 10)
```

### What's in the report

| Section | Shows |
| --- | --- |
| Summary | API requests, sessions, input/output/cache tokens, estimated cost, and the share of cost that ran on router lanes |
| By model | Requests, tokens, effort-level mix and estimated cost per model |
| By lane / agent | The main session, each router lane agent, and any other subagents (Explore, general-purpose, forks) |
| Top projects | Usage per project. Each session counts under the directory it started in, and `.claude/worktrees/*` are folded into their repo |
| Lane/model mismatches | Any router agent that ran on a model other than its configured one (for example, because of an organization override) |
| Router decisions | Decisions and tasks, Jev versus local-rule decisions, average Jev confidence, starting lanes chosen, and actions (escalations, BLOCKED, …) |

Illustrative output (shortened):

```
Model usage — last 24h (2026-09-25T10:49:05+00:00 → 2026-09-26T10:49:05+00:00)
443 API requests across 2 sessions · input 932 · output 577.8k · cache write 2.7M · cache read 102.1M · est. cost $51.01
Output tokens: 424 requests as recorded, 19 requests reconciled with Claude Code session totals.

By lane / agent
lane               agent            requests  input (incl. cache)  output  effort      est. cost
-----------------  ---------------  --------  -------------------  ------  ----------  ---------
—                  main session     310       67.6M                277.8k  medium:310  $33.43
OPUS_LOW           implement-small  48        6.1M                 41.0k   low:48      $2.87
not a router lane  general-purpose  55        13.0M                67.9k   medium:55   $5.46
```

### Where the numbers come from

- **Model usage** is read from Claude Code's own session transcripts (`~/.claude/projects/**/*.jsonl`,
  including `subagents/`). The router doesn't keep a separate usage log, so there's nothing extra to grow.
  Only transcripts modified inside the window are opened, and each API request is counted once, even
  though Claude Code writes one line per content block.
- **Input and cache tokens** come straight from the transcripts and are exact.
- **Output tokens need correcting.** Transcripts often record a turn's output count from the start of
  streaming (a few tokens), especially for tool-call turns, and never write back the final count. The
  report fixes this in one of two ways, and its summary says how many requests used each:
  - **Reconciled:** when a session's `cost-state` record (Claude Code's own per-model totals, including
    subagents and hidden thinking) covers all of the session's activity and the session started inside the
    window, the authoritative output total is split across its requests in proportion to the content each
    one generated. Totals then match Claude Code's `/cost` and headless `total_cost_usd` exactly.
  - **Estimated:** otherwise, each request uses the larger of the recorded count and its generated content
    divided by 2.5 characters per token. Hidden thinking tokens are missed, so these figures run low.
- **Estimated cost** uses the `pricing` table in `policy/policy.json`: USD per million tokens for input,
  output, 5-minute and 1-hour cache writes, and cache reads. These are API-equivalent estimates. On a
  subscription plan they are not your bill; they're a way to compare lanes. Models without a price are
  counted in tokens and marked `*`. Keep the table current by editing it and re-running `./install.sh`.
- **Router decisions** come from the decision log (`~/.local/state/claude-router/decisions.jsonl`).

### Keeping logs small

| Log | Size control |
| --- | --- |
| Decision log `~/.local/state/claude-router/decisions.jsonl` | Pruned to `retention_hours` (default **24**), at most once an hour by the MCP server and whenever the report runs. It holds one short line per decision, with no task text |
| Evidence logs `<repo>/.git/router-evidence/<fingerprint>/` | Folders older than `retention_hours` are deleted on each `collect` |
| Claude Code transcripts `~/.claude/projects/` | Owned by Claude Code, not the router. It deletes them after `cleanupPeriodDays` (30 by default; set it in `~/.claude/settings.json`) |

To keep a longer history, raise `retention_hours` in `policy/policy.json` (for example, `168` for a week),
then re-run `./install.sh`. The report can only cover decisions still in the log. Model usage can reach as
far back as Claude Code keeps transcripts.

---

## Turning it off

Opting out disables the **orchestration policy**: the SessionStart hook tells Claude to ignore it and work
directly. The [dispatch gate](#the-dispatch-gate) also stands down, so the lane agents can be dispatched
freely. The lane agents and `jev` tools stay installed but go unused. The policy switch takes effect when
a session starts, so open a new session or run `/clear` after changing one. The gate checks the opt-out
on every dispatch.

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
| `policy/policy.json` | Lane → agent/model/effort mapping, the escalation ladder, `first_attempt_max_lane` (the cap on a unit's first attempt; default `OPUS_MEDIUM`, remove it to route by predicted class), class descriptions sent to Jev, the confidence threshold, cycle limits, the Jev endpoint/model/timeout, `retention_hours` for the router's logs, and the `pricing` table used by the usage report |
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

Updating refreshes `~/.claude/router/`, the agents and skills it owns, and the MCP registration. It
removes agents and skills dropped by the new version. Your Jev key and any agents or skills you wrote
yourself are left alone.

---

## Uninstalling

```bash
~/.claude/router/uninstall.sh                      # keeps your Jev key
~/.claude/router/uninstall.sh --purge-credentials  # also deletes ~/.config/jev/.env
```

Uninstall removes:
- the `jev` MCP registration
- only the agents and skills the router installed
- the marked import block in `~/.claude/CLAUDE.md`
- the SessionStart hook entry
- the router's decision log
- `~/.claude/router/`

It leaves in place:
- the rest of your settings, and your own agents and skills
- Claude Code's transcripts
- `.git/router-evidence/` folders in your repos; delete them with `rm -rf .git/router-evidence`
- the `settings.json.bak-router-*` backups

---

## Testing and development

```bash
./test.sh              # ruff lint + format check, unit tests, live Jev smoke test
./test.sh --offline    # skip the live Jev test (no key or no network)
```

| Layer | Command | What it proves |
| --- | --- | --- |
| Lint | `ruff check` and `ruff format --check` (in `test.sh`) | Code style and common bug patterns (ruff rules E, F, W, I, B, UP, S, SIM, RUF) |
| Unit | `uv run pytest` in `jev-mcp/` | Strict schemas and size limits; hard gates; ladder routing; the rule that failed, unrun or errored checks block COMPLETE; Jev client retries and error mapping; the key never appears in errors; fingerprints change on staged, unstaged and untracked edits; the usage report counts each request once, filters by window and project, prices tokens, maps lanes and flags mismatches; retention prunes logs |
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

### A dispatch is blocked with "Router gate: dispatching '…' needs a routing decision"
The gate is working as designed. Claude should follow the steps in the message: load the jev tools,
classify the unit with a `task_id` starting with the session id, then dispatch the agent in the returned
route. If it keeps getting blocked:
- **Wrong task_id prefix:** the `task_id` must start with the "Router session id" from the SessionStart
  context.
- **Wrong agent:** the dispatched agent must be the one in the decision's `route`. The block message lists
  the agents this session's unused decisions point to.
- **Reused decision:** each decision allows one dispatch, so a second unit needs its own classification.
- **Forced lane:** to use a lane you asked for, Claude records it with `record_override`.
- **Temporary workaround:** set `CLAUDE_ROUTER=off` or add `.claude/router.off`.

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
Decisions are written to `~/.local/state/claude-router/decisions.jsonl`, one line per decision: tool, IDs,
action or class, route, confidence, and who decided. Task text and evidence bodies are not logged. The log
is pruned to `retention_hours` (24 by default). Summarize it with `/router-report`. Set `ROUTER_LEDGER` to
write it somewhere else.

### `/router-report` shows no usage, or fewer requests than expected
- The report only reads transcripts modified inside the window, and only requests timestamped inside it.
  Try `--hours 168`.
- A non-default config directory needs `CLAUDE_CONFIG_DIR` set when you run the report.
- A `--project` filter matches against the folded project path (for example `~/Dev/statista/router`).
- Costs marked `*` include models that have no price in `policy.json`; add a price to include them.

### `/router-report` shows a lane/model mismatch
A router agent ran on a model other than the one its agent file names. Usually an organization model
override or cap is the cause, or a project agent with the same name. Check `/agents` in that project, and
see [the model access entry](#a-lane-fails-with-a-model-access-error).

---

## Reference

### MCP tools (`mcp__jev__*`)

| Tool | Purpose | Possible outputs |
| --- | --- | --- |
| `get_policy` | Deployed policy version, lanes, ladder and limits | — |
| `record_override` | Records a lane the user explicitly asked for, so the gate allows it | `OVERRIDE` with the route |
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
policy/policy.json      lanes, ladder, classes, limits, Jev endpoint, retention, pricing
skills/router-report/   the /router-report skill
hooks/session-start.sh  prints router ACTIVE/DISABLED into each new session
bin/router-evidence     wrapper for the evidence collector
bin/router-report       wrapper for the usage report
jev-mcp/                Python package (uv, Python 3.14)
  src/jev_router/         server.py (MCP), decisions.py, policy.py, schemas.py, jev.py,
                          evidence.py, usage.py (report), retention.py (log pruning),
                          gate.py (PreToolUse dispatch gate)
  tests/                  pytest suite
  scripts/smoke_live.py   live end-to-end smoke test
benchmarks/             router vs. no-router harness (run.sh, grade.sh, summarize.py), tasks and results
install.sh · uninstall.sh · test.sh · verify-lanes.sh · CHANGELOG.md (policy history)
```

### Files outside the repo

| Path | Owner | Contents |
| --- | --- | --- |
| `~/.claude/router/` | installer | Installed copy and venv |
| `~/.claude/agents/<lane>.md` | installer | Lane agents (tracked in `~/.claude/router/.installed-agents`) |
| `~/.claude/skills/router-report/` | installer | The `/router-report` skill (tracked in `~/.claude/router/.installed-skills`) |
| `~/.claude/CLAUDE.md` | you + installer | Your content, plus the `claude-code-jev-router` import block |
| `~/.claude/settings.json` | you + installer | Your settings, plus one SessionStart hook entry |
| `~/.config/jev/.env` | you | `TYPESAFE_API_KEY`, mode 600 |
| `~/.local/state/claude-router/decisions.jsonl` | MCP server, gate | Sanitized decision log (decisions, overrides, jev errors, gate allows and blocks), pruned to `retention_hours` |
| `~/.local/state/claude-router/gate-<session>.json` | gate | Decisions already used for a dispatch in that session, pruned to `retention_hours` |
| `<repo>/.git/router-evidence/` | evidence collector | Full check logs per fingerprint, pruned to `retention_hours` |
| `~/.claude/projects/` | Claude Code | Session transcripts; `router-report` reads these but never writes them |

---

## Design notes

- **Routes are computed locally.** Jev only picks a class or action from an allowlisted set. The lane,
  model and effort always come from `policy.json`, so Jev can't produce a route the policy doesn't allow.
- **Hard gates come before Jev.** Failed, unrun or errored checks; unsatisfied or unknown criteria;
  out-of-scope diffs; and known failures are all evaluated locally. Jev is only asked about what's left
  after that.
- **Escalate on evidence, not prediction.** First attempts are capped at OPUS_MEDIUM; stronger lanes need a
  verified failure. Low-confidence classifications hedge *down* to the cheaper of Jev's top two classes,
  because with a verification loop a too-low guess costs one retry, while a too-high guess costs a
  stronger lane on every run. Security-sensitive work is floored at HIGH. `FABLE_XHIGH` is never a first
  classification.
- **Size the process to the task.** Single-unit tasks run in lightweight mode, with no dispatch and checks
  at the end. Full orchestration, with contracts, workers in fresh contexts and evidence, is reserved for
  multi-part, long-running or security-sensitive work.
- **Wait for workers.** The orchestrator never ends its turn with a worker still running. In headless
  sessions, that would end the session and lose the verification and the report.
- **Retries require a new hypothesis.** Repeating an unchanged failed attempt uses up budget without adding
  evidence.
- **Credentials:** the MCP server process is the only thing that reads the key, from `TYPESAFE_API_KEY` or
  `~/.config/jev/.env`. The key is never logged or returned. This is a same-user boundary, not strict
  isolation: a worker with Bash could still read the file. For strict isolation, run the server as a
  separate user or service behind an authenticated HTTP transport.
- **Jev client:** calls the documented `POST https://api.typesafe.ai/v1/systemone` endpoint with httpx
  (one retry with jitter on transport errors and 429/5xx, no retry on 401/403). The official `typesafe-sdk`
  package could replace it.
