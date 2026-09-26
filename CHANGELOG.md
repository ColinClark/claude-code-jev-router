# Changelog

Router policy versions (`policy/policy.json` → `policy_version`) and notable tooling changes. Benchmark
evidence for each policy change is in [`benchmarks/README.md`](benchmarks/README.md).

## Policy 1.6: size the process to the task (current)
- **Step 0:** classify the whole task first, then choose a mode.
- **Lightweight mode:** single-unit tasks routed at OPUS_MEDIUM or lower are implemented directly, with the
  repo's checks run at the end. After two failed attempts the session switches to full mode.
- **Full mode:** reserved for multi-part, long-running or security-sensitive work.
- **Result:** parity with an Opus 5.5 baseline on small and medium tasks, 27% cheaper and faster on the
  largest.

## Policy 1.5: wait for workers
- The orchestrator must wait for every dispatched worker before continuing or finishing. A headless Sonnet
  orchestrator had ended its session while a worker was still running.

## Policy 1.4: escalate on evidence, not prediction
- **Capped first attempts:** `first_attempt_max_lane` (OPUS_MEDIUM). OPUS_HIGH and Fable are reached only
  via `decide_escalation` after a verified failure. Security-sensitive units still start at OPUS_HIGH.
- **Hedge down:** low-confidence classifications take the cheaper of Jev's top two classes (previously the
  stronger).

## Policy 1.3
- SMALL lane back to Opus 5.5 low effort (Sonnet 5 saved nothing in benchmarks).

## Policy 1.2
- SMALL lane moved to Sonnet 5 medium; `install.sh --set-model=MODEL`.

## Policy 1.1: enforce routing
- **Dispatch gate:** a PreToolUse hook on the Agent tool blocks `implement-*` dispatches without an unused,
  session-scoped routing decision.
- **Mandatory classification:** Jev classifies every unit. `record_override` covers user-named lanes, and
  the SessionStart hook prints the session id.

## Policy 1.0
- Initial lanes, Jev MCP decision tools, evidence collector and orchestration policy.

## Tooling
- **Usage reporting.** `router-report` and `/router-report` report model usage from Claude Code
  transcripts, deduplicated by request. Output tokens are reconciled with the `cost-state` session totals,
  because transcripts often record only the value at the start of streaming. Includes decision-log and
  evidence-log retention.
- **Benchmarks.** `benchmarks/`: a router vs. no-router harness with hidden acceptance suites, and four
  tasks.
