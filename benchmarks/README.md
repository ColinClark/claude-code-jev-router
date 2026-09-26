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

Five configurations, 2 runs each. "Orchestrator" is the main-session model at medium effort. Policy 1.1
routes SMALL units to Opus 5.5 at low effort; policy 1.2 routes them to Sonnet 5 at medium effort.

| Configuration | Hidden acceptance | Own tests | Mean cost | Mean wall time | Where the cost went |
| --- | ---: | ---: | ---: | ---: | --- |
| **baseline · Opus 5.5** (router off) | 10/10, 10/10 | 24, 17 | **$0.53** | **2.0 min** | main session only |
| baseline · Sonnet 5 (router off) | 10/10, 10/10 | 18, 26 | $0.53 | 2.8 min | main session only |
| router · Opus 5.5 orchestrator · policy 1.1 | 10/10, 10/10 | 40, 44 | $1.24 | 4.7 min | orchestrator ~53%, OPUS_HIGH ~30%, OPUS_LOW ~16% |
| router · Opus 5.5 orchestrator · policy 1.2 | 10/10, 10/10 | 45, 45 | $1.38 | 6.0 min | orchestrator ~53%, OPUS_HIGH ~30%, SONNET_MEDIUM ~16% |
| router · Sonnet 5 orchestrator · policy 1.2 | 10/10, 10/10 | 53, 55 | $1.69 | 9.8 min | OPUS_HIGH ~48%, orchestrator ~38%, SONNET_MEDIUM ~13% |

Jev's routing was consistent across all router runs: scaffold → SMALL (confidence 1.0), store with locking
→ HIGH (0.83–0.88), CLI → SMALL (0.88–1.0). The Sonnet orchestrator also split out a separate "tests"
unit, which Jev classified as HIGH (0.94–0.95). The dispatch gate allowed every routed dispatch and blocked
none.

### What this shows

- **Every configuration was correct.** All 10 runs passed all 10 hidden acceptance tests, including no lost
  updates from 4 concurrent writer processes and no leftover temp files.
- **On this task, the router costs 2.3–3.2× more and takes 2.3–4.9× longer.** It spends turns on things
  the baseline skips: splitting the work, classifying each unit, writing a work contract for each worker,
  collecting evidence independently, and reviewing the result. Router runs write about twice as many tests
  of their own, but the hidden suite shows no correctness difference.
- **Cheaper models didn't produce cheaper runs.** Sonnet 5 costs half of Opus 5.5 per token but needed
  more requests for the same work:
  - The Sonnet small lane used 18–21 requests where Opus at low effort used 7, and its share of cost stayed
    about the same (~16%).
  - The Sonnet baseline cost the same as the Opus baseline ($0.53) and was slower.
  - The Sonnet orchestrator split the work more finely. Its extra "tests" unit went to OPUS_HIGH, so more
    of the cost landed on Opus, and runs took about 10 minutes.
  - Price per token is not price per task.
- **Routing itself behaved correctly.** Jev reliably separated the routine parts from the hard part, and
  the gate made sure every dispatch followed its decision.

### Recommendation from this data

- **Orchestrator:** keep Opus 5.5 at medium effort. A Sonnet orchestrator was both slower and more
  expensive here.
- **SMALL lane:** Opus 5.5 at low effort (policy 1.1) beat Sonnet 5 at medium effort (policy 1.2) on this
  task, $1.24 versus $1.38. Two runs each is a small sample, though.
- **Small, well-specified tasks:** the router's overhead isn't repaid. Turn it off per task ("no router")
  or per project (`.claude/router.off`), or tune the policy so the orchestrator does a task directly when
  Jev classifies the whole thing as a single SMALL or MEDIUM unit.

### What to test next

The tinykv result is one data point: a small, fully specified task that every configuration solves. The
router is designed for cases this benchmark doesn't exercise:
- **Hard or ambiguous work,** where a single session flounders or burns tokens retrying. Escalation with
  evidence, retry budgets and independent verification matter there.
- **Tasks where a single cheaper session fails,** so routing hard units to a stronger lane changes the
  outcome, not just the cost.
- **Long tasks,** where keeping each unit's context separate avoids one ever-growing, expensive session.

Useful next benchmarks would be a task with a real debugging trap, a larger multi-module feature, and more
runs per configuration.

### History: why the dispatch gate exists

The first router run of this task, before the gate existed (policy 1.0), skipped Jev entirely. The
orchestrator judged the class "obvious" and sent the whole task, locking included, to one `implement-medium`
worker ($0.93, correct result). Asked afterwards, Jev split the same task three ways and put the locking at
HIGH with 0.87 confidence. Prompt instructions alone didn't make routing happen, so policy 1.1 added the
PreToolUse dispatch gate and mandatory per-unit classification. All router runs above use policy 1.1 or
later.

### A note on the hidden suite

The first version of the acceptance suite required `Store.get()` to return `None` for a missing or expired
key. Two Sonnet runs raised `KeyError` instead and failed 3 tests. The prompt only says expired keys are
"never returned", and `KeyError` satisfies that, so the suite was corrected to accept either behavior and
every run was regraded. The corrected suite still rejects any run that returns a value for a missing key.

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

- **Small samples.** Two runs per configuration show direction, not statistical significance. LLM runs
  vary; add more runs before drawing strong conclusions.
- **Turns aren't comparable across models.** `num_turns` counts differently between models: the Sonnet
  orchestrator reports 2–3. Compare cost, wall time and output tokens instead.
- **Costs are API-equivalent** (list prices, as reported by Claude Code). On a subscription plan they are a
  way to compare, not your bill.
- **The baseline isn't completely "clean".** It uses the real opt-out (`CLAUDE_ROUTER=off`), so the policy
  text is still imported but the session is told to ignore it, and the gate stands down. That matches what
  a user who turns the router off gets.
