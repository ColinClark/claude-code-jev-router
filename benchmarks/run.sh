#!/usr/bin/env bash
# Run one benchmark task headlessly, with or without the smart router, and record the results.
#
#   benchmarks/run.sh tinykv router      # router active (the default after install)
#   benchmarks/run.sh tinykv baseline    # CLAUDE_ROUTER=off: same model and effort, no routing
#
# Each run starts from a fresh git repo seeded from benchmarks/<task>/seed and gets the same prompt,
# orchestrator model, effort and budget. Afterwards the harness independently re-runs the checks and
# saves everything under benchmarks/results/<task>/<run-id>/:
#   meta.json        mode, model, effort, budget, versions, timing
#   result.json      Claude Code's headless result (authoritative total cost and per-model usage)
#   report.json      router-report for this run's project (per-model and per-lane breakdown)
#   decisions.jsonl  this session's router decisions and dispatch-gate events
#   checks.json      independent pytest / ruff results, plus logs
#   code/            the files the run produced (tracked and untracked, ignored files excluded)
#
# Env overrides: BENCH_MODEL (claude-opus-5-5), BENCH_EFFORT (medium), BENCH_BUDGET_USD (15),
# BENCH_WORKDIR (scratch directory for the generated repos; default $TMPDIR).
set -uo pipefail

TASK="${1:?usage: run.sh <task> <router|baseline>}"
MODE="${2:?usage: run.sh <task> <router|baseline>}"
case "$MODE" in router|baseline) ;; *) echo "mode must be router or baseline" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$ROOT/$TASK"
[[ -f "$TASK_DIR/prompt.md" && -d "$TASK_DIR/seed" ]] || { echo "unknown task: $TASK" >&2; exit 2; }
ROUTER_HOME="${CLAUDE_ROUTER_HOME:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/router}"
REPORT="$ROUTER_HOME/bin/router-report"
LEDGER="${ROUTER_LEDGER:-$HOME/.local/state/claude-router/decisions.jsonl}"
MODEL="${BENCH_MODEL:-claude-opus-5-5}"
EFFORT="${BENCH_EFFORT:-medium}"
BUDGET="${BENCH_BUDGET_USD:-15}"

RUN_ID="$TASK-$MODE-$(date -u +%Y%m%dT%H%M%SZ)-$$"
WORK="${BENCH_WORKDIR:-${TMPDIR:-/tmp}}/claude-router-bench/$RUN_ID"
OUT="$ROOT/results/$TASK/$RUN_ID"
mkdir -p "$WORK" "$OUT"

# Fresh repository from the seed.
cp -R "$TASK_DIR/seed/." "$WORK/"
git -C "$WORK" init -q
git -C "$WORK" add -A
git -C "$WORK" -c user.name=bench -c user.email=bench@example.com commit -qm "seed"

if [[ "$MODE" == baseline ]]; then export CLAUDE_ROUTER=off; else unset CLAUDE_ROUTER; fi

echo "[$RUN_ID] running in $WORK"
start=$(date +%s)
(cd "$WORK" && claude -p "$(cat "$TASK_DIR/prompt.md")" \
    --model "$MODEL" --effort "$EFFORT" --max-budget-usd "$BUDGET" --output-format json) \
  > "$OUT/result.json" 2> "$OUT/stderr.log"
claude_rc=$?
end=$(date +%s)
unset CLAUDE_ROUTER

# Independent verification of the produced workspace.
(cd "$WORK" && uv run --quiet pytest -q --junitxml="$OUT/pytest.xml") > "$OUT/pytest.log" 2>&1; pytest_rc=$?
(cd "$WORK" && uv run --quiet ruff check .) > "$OUT/ruff.log" 2>&1; ruff_rc=$?
# Count from the JUnit report: a project's own pytest options (e.g. -qq) can hide the summary line.
read -r tests failed errors skipped < <(python3 "$ROOT/junit_counts.py" "$OUT/pytest.xml")
passed=$(( tests - failed - errors - skipped ))
jq -n --argjson p "$pytest_rc" --argjson r "$ruff_rc" --argjson np "${passed:-0}" --argjson nf "${failed:-0}" \
  '{pytest: {exit_code: $p, passed: $np, failed: $nf}, ruff: {exit_code: $r}}' > "$OUT/checks.json"

# Usage for this run's project only, and this session's router decisions.
hours=$(( (end - start) / 3600 + 1 ))
"$REPORT" --hours "$hours" --project "$RUN_ID" --format json > "$OUT/report.json" 2>/dev/null || echo '{}' > "$OUT/report.json"
session="$(jq -r '.session_id // empty' "$OUT/result.json" 2>/dev/null)"
if [[ -n "$session" && -f "$LEDGER" ]]; then
  jq -c --arg s "$session:" 'select((.task_id // "") | startswith($s))' "$LEDGER" > "$OUT/decisions.jsonl"
else
  : > "$OUT/decisions.jsonl"
fi

# Snapshot of the produced code (ignored files such as .venv excluded).
mkdir -p "$OUT/code"
(cd "$WORK" && git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$OUT/code/")

jq -n --arg run "$RUN_ID" --arg task "$TASK" --arg mode "$MODE" --arg model "$MODEL" --arg effort "$EFFORT" \
  --arg budget "$BUDGET" --arg claude "$(claude --version 2>/dev/null)" \
  --arg policy "$(jq -r .policy_version "$ROUTER_HOME/policy/policy.json" 2>/dev/null)" \
  --argjson start "$start" --argjson end "$end" --argjson rc "$claude_rc" --arg session "$session" \
  '{run_id: $run, task: $task, mode: $mode, model: $model, effort: $effort, budget_usd: ($budget|tonumber),
    claude_code: $claude, router_policy: (if $mode == "router" then $policy else null end),
    session_id: $session, started: $start, ended: $end, wall_seconds: ($end - $start), claude_exit: $rc}' \
  > "$OUT/meta.json"

echo "[$RUN_ID] done: claude exit $claude_rc, pytest exit $pytest_rc ($passed passed), ruff exit $ruff_rc"
echo "[$RUN_ID] results in $OUT"
