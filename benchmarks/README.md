# Benchmarks: router vs. no router

The same task runs headlessly in two modes, and the results are compared on cost, time and correctness:

- **baseline:** `CLAUDE_ROUTER=off`. One Claude Code session (Opus 5.5, medium effort) does everything
  itself.
- **router:** the installed smart router. The same session becomes an orchestrator. It splits the task
  into units, has Jev classify each unit, dispatches lane agents (the gate enforces this), and verifies the
  results itself.

Correctness is judged two ways: by the tests each run wrote for itself, and by a **hidden acceptance
suite** written only from the prompt. Neither mode ever sees that suite.

## tinykv

A small persistent key-value store: a uv project, a `Store` class with per-key expiry (TTL), atomic JSON
writes, an `fcntl` lock so concurrent writer processes don't lose updates, a CLI, and tests. The pieces
range in difficulty: the scaffolding and CLI are routine, and the locking and atomic persistence are the
hard part.

Full per-run results: [`results/tinykv/RESULTS.md`](results/tinykv/RESULTS.md). The generated code for
every run is under `results/tinykv/<run>/code/`.

| | baseline (router off) | router |
| --- | ---: | ---: |
| Runs | 2 | 2 |
| Hidden acceptance (10 tests) | 10/10, 10/10 | 10/10, 10/10 |
| Tests the run wrote itself | 24, 17 | 40, 44 |
| Mean cost | **$0.53** | $1.24 |
| Mean wall time | **2.0 min** | 4.7 min |
| Mean output tokens | 10.4k | 26.1k |
| Where the work ran | main session only | orchestrator ~53%, `implement-high` ~30%, `implement-small` ~16% of cost |
| Jev routing (both router runs) | — | scaffold → SMALL/OPUS_LOW (1.0) · store → HIGH/OPUS_HIGH (0.85–0.88) · CLI → SMALL/OPUS_LOW (0.95–0.97) |

### What this shows

- **Both modes were correct.** Every run passed all 10 hidden acceptance tests, including no lost updates
  from 4 concurrent writer processes and no leftover temp files. On a task this well specified, Opus 5.5
  at medium effort gets it right on its own.
- **The router cost about 2.3× more and took about 2.3× longer.** It spends turns on things the baseline
  skips: splitting the work, classifying each unit, writing a work contract for each worker, collecting
  evidence independently after each unit, and reviewing the result. The router runs also wrote roughly
  twice as many tests. That's more thoroughness, but the hidden suite shows no correctness difference on
  this task.
- **Routing did what it should.** Jev consistently separated the routine parts from the hard part and sent
  the locking and persistence unit *up* to OPUS_HIGH. The dispatch gate allowed each routed dispatch and
  blocked none.
- **There was no cheaper model to route to.** The implementation lanes are all Opus 5.5 at different
  effort levels, and the orchestrator runs on Opus 5.5 too. Most of the router's potential savings come
  from sending work to a cheaper model than the one orchestrating; that couldn't happen here.

### When the router should pay off, and what to test next

The tinykv result is one data point: a small, fully specified task. The router is designed for cases this
benchmark doesn't exercise:
- **Hard or ambiguous work,** where a single session flounders or burns tokens retrying. Escalation with
  evidence, retry budgets and independent verification matter there.
- **Mixed-price lanes,** for example an Opus orchestrator with bulk work on Sonnet or Haiku lanes, or a
  Fable escalation used only when needed instead of running everything on Fable.
- **Long tasks,** where keeping each unit's context separate avoids one ever-growing, expensive session.

Useful next benchmarks would be a task with a real debugging trap, a larger multi-module feature, and a run
with the orchestrator on a more expensive model than the workers. Tuning is also worth trying: for
example, letting the orchestrator handle a whole task directly when Jev classifies it as a single SMALL or
MEDIUM unit.

### History: why the dispatch gate exists

The first router run of this task, before the gate existed (policy 1.0), skipped Jev entirely. The
orchestrator judged the class "obvious" and sent the whole task, locking included, to one `implement-medium`
worker ($0.93, correct result). Asked afterwards, Jev split the same task three ways and put the locking at
HIGH with 0.87 confidence. Prompt instructions alone didn't make routing happen, so policy 1.1 added the
PreToolUse dispatch gate and mandatory per-unit classification. Both runs above use policy 1.1.

## Running it

Requires the router to be installed (`./install.sh`), plus `claude`, `uv`, `jq` and `rsync`. Each run
spends real API credit, roughly $0.50–$1.50 for tinykv.

```bash
benchmarks/run.sh tinykv baseline        # one run with the router off
benchmarks/run.sh tinykv router          # one run with the router on
benchmarks/grade.sh tinykv               # hidden acceptance tests against every run's code
python3 benchmarks/summarize.py tinykv   # regenerate results/tinykv/RESULTS.md
```

Runs can execute in parallel; each gets its own scratch repo and Claude session. The settings below can be
changed through environment variables:

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
| `checks.json`, `pytest.log`, `ruff.log` | The harness's independent re-run of the project's own checks |
| `acceptance.json`, `acceptance.log` | Hidden acceptance results (from `grade.sh`) |
| `code/` | The files the run produced (ignored files such as `.venv` excluded) |

### Adding a task

Create `benchmarks/<task>/prompt.md`, a `seed/` directory (the starting repo contents) and an
`acceptance/` directory of pytest tests written only from the prompt. Then run both modes, grade and
summarize.

### Caveats

- **Small samples.** Two runs per mode show direction, not statistical significance. LLM runs vary; add
  more runs before drawing strong conclusions.
- **Costs are API-equivalent** (list prices, as reported by Claude Code). On a subscription plan they are a
  way to compare, not your bill.
- **The baseline isn't completely "clean".** It uses the real opt-out (`CLAUDE_ROUTER=off`), so the policy
  text is still imported but the session is told to ignore it, and the gate stands down. That matches what
  a user who turns the router off gets.
