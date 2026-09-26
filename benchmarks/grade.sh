#!/usr/bin/env bash
# Grade benchmark runs against the task's hidden acceptance tests.
#
#   benchmarks/grade.sh tinykv              grade every run under benchmarks/results/tinykv/
#   benchmarks/grade.sh tinykv RUN_DIR...   grade specific runs
#
# Each run's generated code is copied to a scratch directory, installed with uv, and the acceptance tests in
# benchmarks/<task>/acceptance/ are run against it. Writes acceptance.json and acceptance.log into the run dir.
set -uo pipefail

TASK="${1:?usage: grade.sh <task> [run_dir...]}"
shift
ROOT="$(cd "$(dirname "$0")" && pwd)"
ACCEPT="$ROOT/$TASK/acceptance"
[[ -d "$ACCEPT" ]] || { echo "no acceptance tests for $TASK" >&2; exit 2; }
if [[ $# -eq 0 ]]; then set -- "$ROOT/results/$TASK"/*/; fi

for run in "$@"; do
  run="${run%/}"
  [[ -d "$run/code" ]] || continue
  scratch="$(mktemp -d)"
  cp -R "$run/code/." "$scratch/"
  cp -R "$ACCEPT" "$scratch/_acceptance"
  (cd "$scratch" && uv run --quiet --with pytest pytest -v --color=no -p no:cacheprovider _acceptance) \
    > "$run/acceptance.log" 2>&1
  rc=$?
  passed="$(grep -Eo '[0-9]+ passed' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  failed="$(grep -Eo '[0-9]+ failed' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  errors="$(grep -Eo '[0-9]+ errors?' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  # Total = collected cases; if collection itself failed (e.g. the package doesn't import), use the known count.
  total=$(( ${passed:-0} + ${failed:-0} ))
  if [[ $total -eq 0 && -f "$ACCEPT/EXPECTED_TOTAL" ]]; then total="$(cat "$ACCEPT/EXPECTED_TOTAL")"; fi
  # Per-test outcomes from pytest -v lines like "_acceptance/test_x.py::test_name[param] PASSED".
  grep -Eo '::[^ ]+ (PASSED|FAILED|ERROR)' "$run/acceptance.log" \
    | jq -R 'capture("::(?<name>[^ ]+) (?<outcome>[A-Z]+)")' | jq -s 'map({(.name): .outcome}) | add // {}' \
    > "$run/acceptance-tests.json"
  jq -n --argjson rc "$rc" --argjson p "${passed:-0}" --argjson f "${failed:-0}" --argjson e "${errors:-0}" \
    --argjson t "${total:-0}" --slurpfile tests "$run/acceptance-tests.json" \
    '{exit_code: $rc, passed: $p, failed: $f, errors: $e, total: $t, tests: $tests[0]}' > "$run/acceptance.json"
  rm -f "$run/acceptance-tests.json"
  echo "$(basename "$run"): acceptance ${passed:-0}/${total} passed (exit $rc)"
  rm -rf "$scratch"
done
