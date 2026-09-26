# Benchmarks: router vs. no router

Each task runs headlessly in two modes, and the results are compared on cost, time and correctness:

- **baseline:** `CLAUDE_ROUTER=off`. One Claude Code session does everything itself.
- **router:** the installed smart router, with the orchestrator on the same model and effort.

Correctness is judged by a **hidden acceptance suite** written only from each prompt, which no run ever
sees. For the engine tasks the suite is graded against a reference implementation: `sqlite3` for minisql,
`re` for miniregex. Costs are Claude Code's own `total_cost_usd` (API list prices).

## Result: where the router works

The final configuration is **policy 1.6**: evidence-driven escalation, with the process sized to the task.
Against a strong single-model baseline (Opus 5.5, medium effort), it matched quality everywhere, cost
about the same on small and medium tasks, and was **27% cheaper and 27% faster on the largest task**:

| Task | Size | Hidden acceptance (all runs) | Opus 5.5 baseline | Router, policy 1.6 | Router vs. baseline |
| --- | --- | --- | ---: | ---: | --- |
| [tinykv](tinykv/prompt.md) | small feature | 10/10 | $0.53 · 2.0 min (n=2) | $0.57 · 1.7 min (n=2) | parity (+8% cost) |
| [billing](billing/prompt.md) | audit a codebase, 6 planted bugs | 25/25, 6/6 bugs | $0.48 · 1.4 min (n=2) | $0.48 · 1.3 min (n=2) | parity |
| [miniregex](miniregex/prompt.md) | regex engine, fuzzed against `re` | 77/77 | $2.26 · 30 min (n=4) | $2.02 · 28 min (n=4) | parity (−11%; ranges overlap) |
| [minisql](minisql/prompt.md) | SQL engine, graded against SQLite | 79/79 | $5.23 · 22 min (n=4) | **$3.82 · 16 min** (n=4) | **−27% cost, −27% time**; ranges don't overlap ($3.32–4.08 vs. $4.74–5.64) |

It also compares well against other baselines:
- **Strongest model for everything** (Fable 5.1, high effort): $1.61 on tinykv and $1.16 on billing, with
  the same quality. Even the earlier router policies cost 20–23% less than that.
- **A cheaper model for everything** (Sonnet 5, medium effort): it **failed** minisql (69/79 in both runs)
  and one miniregex run (76/77). A Sonnet orchestrator with the router scored 79/79 on minisql at $3.47,
  cheaper than the all-Opus baseline.

Full per-run tables: [`results/<task>/RESULTS.md`](results/). The generated code for every run is under
`results/<task>/<run>/code/`.

### What actually produces the gains

- **Predicted difficulty is a bad reason to spend more.** Jev reliably spotted the hard parts, but "hard"
  units such as a SQL or regex engine were handled fine by Opus at medium effort. Sending them to Opus
  high effort or Fable on prediction cost 2–4× for no quality gain. Policy 1.4 therefore caps first
  attempts at OPUS_MEDIUM, and the stronger lanes are reached only after a *verified* failure.
- **Process discipline matters more than model routing.** In all eight policy 1.6 runs the orchestrator
  chose lightweight mode: it worked in the main session, ran the checks once at the end, and escalated only
  on evidence. No lane agents were needed and no escalation fired. On minisql this produced about 25% fewer
  output tokens and fewer cache re-reads than the baseline session, with the same model and effort. **Part
  of the router's value is therefore its operating policy, not the multi-model machinery.** The lanes and
  escalation are the safety net for work that actually fails, and these tasks never triggered them.
- **Context isolation helps on long tasks, and costs on short ones.** Dispatching the engine to a
  fresh-context worker (policies 1.4 and 1.5) cut minisql's cache re-reads from about 7.5M to 2–4M tokens.
  On miniregex, whose baseline session never grew long, the same split cost extra in cache writes.

### Where the router does not help

- **Small, well-specified tasks.** The best case is parity. Earlier policies cost 30–130% more, from
  orchestration ceremony and unnecessary delegation.
- **Tasks a strong baseline already solves.** No run of Opus 5.5 at medium effort failed any hidden test,
  so the router's escalation machinery never had a failure to recover from.

## How we got here: every policy tested

| Policy | Change | Effect in these benchmarks |
| --- | --- | --- |
| 1.0 | Prompt-only routing | The orchestrator skipped Jev entirely ("obvious") and sent everything to one worker |
| 1.1 | Dispatch gate: every unit classified, every dispatch backed by a routing decision | Routing worked as designed; cost 2.3× the baseline on tinykv |
| 1.2 | SMALL units → Sonnet 5 | No saving: Sonnet needed about 2.5× the requests. Reverted in 1.3 |
| 1.3 | Predictive routing (hard units → OPUS_HIGH / Fable; hedge **up** when unsure) | 2–4× the baseline on minisql and miniregex, with 86–95% of the cost in the escalated unit |
| 1.4 | **Evidence-driven:** first attempts capped at OPUS_MEDIUM, hedge **down** when unsure | minisql router cheaper than baseline for the first time |
| 1.5 | Wait for every worker before finishing (a headless Sonnet orchestrator had quit early) | Fixed incomplete runs |
| 1.6 | **Size the process:** lightweight mode for single-unit tasks, full orchestration for multi-part or long work | Parity on small tasks; −27% on minisql |

## Tasks

| Task | What it tests | Hidden suite |
| --- | --- | --- |
| [tinykv](tinykv/) | Small feature: persistent key-value store with TTL, atomic writes, `fcntl` locking, CLI | 10 tests, written from the prompt |
| [billing](billing/) | Audit and fix an existing codebase against its spec: 6 planted bugs, only 2 of them reported in `ISSUE.md` | 25 tests grouped by bug; proven against a bug-free [reference](billing/reference/) that passes all 25 while the seed fails every bug group |
| [minisql](minisql/) | Large build: SQL engine (joins, NULL logic, GROUP BY/HAVING, ORDER BY, UPDATE/DELETE) | 79 cases compared against `sqlite3`, including 250 seeded random queries |
| [miniregex](miniregex/) | Hard build: backtracking regex engine with exact `re` group semantics | 77 cases compared against `re`, including 800 fuzzed patterns × 6 texts |

### Corrections to the hidden suites

Each suite was validated before use: with a `sqlite3`/`re`-backed "cheat" implementation that must pass
everything except the no-cheating check, or with a bug-free reference. Three flaws were still found in
real runs and fixed, and every run was regraded:
1. **tinykv** required `get()` to return `None` for a missing key. The prompt only says such keys are
   "never returned", so raising `KeyError` is now accepted too.
2. **minisql**'s no-`sqlite3` check matched comments that named SQLite's C functions (a run had ported
   `sqlite3FpDecode`). It now inspects real imports via the AST.
3. **minisql**'s `ORDER BY 1` (a column position) is implied by "match SQLite" but not spelled out in the
   prompt. Sonnet's failures include it; Opus handled it. It was kept, with this note.

## Running it

Requires the router to be installed (`./install.sh`), plus `claude`, `uv`, `jq` and `rsync`. Each run
spends real API credit: about $0.50 for tinykv and billing, $2–5 for miniregex and minisql. The full set
of results here (67 runs) cost $175 at list prices.

```bash
benchmarks/run.sh tinykv baseline        # one run with the router off
benchmarks/run.sh tinykv router          # one run with the router on
benchmarks/grade.sh tinykv               # hidden acceptance tests against every run's code
python3 benchmarks/summarize.py tinykv   # regenerate results/tinykv/RESULTS.md
```

Runs can execute in parallel; each gets its own scratch repo and Claude session. **Don't run
`./install.sh` while benchmarks are running:** it rebuilds the environment that live sessions' `jev` MCP
server runs from. One run was killed that way and excluded. These settings can be changed through
environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BENCH_MODEL` | `claude-opus-5-5` | Orchestrator / main-session model for both modes |
| `BENCH_EFFORT` | `medium` | Effort for the main session |
| `BENCH_BUDGET_USD` | `15` | `--max-budget-usd` cap per run |
| `BENCH_WORKDIR` | `$TMPDIR` | Where the scratch repos are created |

### What each run records

`benchmarks/results/<task>/<run-id>/`:

| File | Contents |
| --- | --- |
| `meta.json` | Mode, model, effort, budget, Claude Code version, router policy version, timing |
| `result.json` | Claude Code's headless result: authoritative `total_cost_usd` and per-model usage |
| `report.json` | `router-report` for this run's project: per-model and per-lane usage |
| `decisions.jsonl` | This session's Jev decisions and dispatch-gate events |
| `checks.json`, `pytest.log`, `pytest.xml`, `ruff.log` | The harness's independent re-run of the project's own checks (test counts come from the JUnit report) |
| `acceptance.json`, `acceptance.log` | Hidden acceptance results with per-test outcomes (from `grade.sh`) |
| `code/` | The files the run produced (ignored files such as `.venv` excluded) |

### Adding a task

Create `benchmarks/<task>/prompt.md`, a `seed/` directory (the starting repo contents), an `acceptance/`
directory of pytest tests written only from the prompt, and `acceptance/EXPECTED_TOTAL`. Validate the suite
against a reference or cheat implementation before running models. Name tests `test_bugN_*` to get a
per-bug scorecard. Then run both modes, grade and summarize.

### Caveats

- **Small samples.** n=2 to n=4 per configuration. Run-to-run cost varies by ±15–20%. Only the minisql
  result has non-overlapping ranges; treat the rest as parity.
- **Costs are API-equivalent** (list prices, as reported by Claude Code). On a subscription plan they are a
  way to compare, not your bill.
- **The baseline uses the real opt-out** (`CLAUDE_ROUTER=off`): the policy text is still imported, but the
  session is told to ignore it and the gate stands down. That's what a user who turns the router off gets.
- **Turns aren't comparable across models.** `num_turns` counts differently between models; compare cost,
  wall time and output tokens instead.
- **Lightweight mode's gains may not need the router.** Some of the 1.6 savings come from the operating
  policy (explicit contract, checks at the end, escalate on evidence), which a plain CLAUDE.md could also
  carry. Isolating that effect is an obvious next experiment.
