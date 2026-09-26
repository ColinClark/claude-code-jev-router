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
  (cd "$scratch" && uv run --quiet --with pytest pytest -q -p no:cacheprovider _acceptance) > "$run/acceptance.log" 2>&1
  rc=$?
  passed="$(grep -Eo '[0-9]+ passed' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  failed="$(grep -Eo '[0-9]+ failed' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  errors="$(grep -Eo '[0-9]+ errors?' "$run/acceptance.log" | tail -1 | grep -Eo '[0-9]+' || echo 0)"
  total="$(cat "$ACCEPT"/test_*.py | grep -c '^def test_')"
  jq -n --argjson rc "$rc" --argjson p "${passed:-0}" --argjson f "${failed:-0}" --argjson e "${errors:-0}" \
    --argjson t "${total:-0}" '{exit_code: $rc, passed: $p, failed: $f, errors: $e, total: $t}' > "$run/acceptance.json"
  echo "$(basename "$run"): acceptance ${passed:-0}/${total} passed (exit $rc)"
  rm -rf "$scratch"
done
