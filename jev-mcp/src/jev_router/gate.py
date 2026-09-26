"""router-gate: PreToolUse hook that only lets routed implementation agents be dispatched.

Claude Code runs this before every Agent tool call, passing the hook event as JSON on stdin. A dispatch
to an implementation lane agent (implement-small ... implement-extreme) is allowed only when this
session has an unused routing decision in the decision log that names that agent:
  - classify_task (the normal case),
  - decide_escalation with a route (ESCALATE, DEESCALATE or KEEP), or
  - record_override (a lane the user explicitly asked for).
Decisions belong to a session through their task_id, which must start with "<session_id>:". Each
decision allows one dispatch.

Degraded mode: if Jev returned JEV_UNAVAILABLE in this session recently, dispatches are allowed so an
outage falls back to local routing instead of blocking all work. Read-only agents (lookup, research)
and non-router agents are never gated, and nothing is gated when the router is turned off.

Exit 0 allows the call. Exit 2 blocks it, and Claude Code shows stderr to the model.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import retention
from .policy import Policy

DECISION_WINDOW_SECONDS = 3600
DEGRADED_WINDOW_SECONDS = 900
ROUTING_TOOLS = {"classify_task", "decide_escalation", "record_override"}
LOAD_JEV = (
    "select:mcp__jev__classify_task,mcp__jev__decide_escalation,mcp__jev__record_override,"
    "mcp__jev__assess_progress,mcp__jev__assess_completion,mcp__jev__get_policy"
)


def router_disabled(project_dir: str | None, env: dict) -> bool:
    if env.get("CLAUDE_ROUTER", "on") == "off":
        return True
    return bool(project_dir) and (Path(project_dir) / ".claude" / "router.off").exists()


def _state_path(ledger: Path, session: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:100] or "unknown"
    return ledger.parent / f"gate-{safe}.json"


def _load_used(path: Path) -> set[str]:
    try:
        return set(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def evaluate(event: dict, policy: Policy, ledger: Path, env: dict, now: float | None = None) -> tuple[bool, str]:
    """Return (allowed, message). Records allows and blocks in the decision log."""
    now = now if now is not None else time.time()
    agent = (event.get("tool_input") or {}).get("subagent_type")
    gated = {policy.lanes[lane]["agent"]: lane for lane in policy.ladder}
    if agent not in gated:
        return True, ""
    if router_disabled(env.get("CLAUDE_PROJECT_DIR") or event.get("cwd"), env):
        return True, ""

    session = str(event.get("session_id") or "")
    prefix = f"{session}:"
    entries = [
        e
        for e in retention.read_entries(ledger, now - DECISION_WINDOW_SECONDS)
        if str(e.get("task_id", "")).startswith(prefix)
    ]
    state = _state_path(ledger, session)
    used = _load_used(state)

    def log(action: str, request_id: str | None = None) -> None:
        retention.append_entry(
            ledger,
            {
                "tool": "dispatch_gate",
                "task_id": f"{session}:gate",
                "action": action,
                "route": {"lane": gated[agent], "agent": agent},
                "request_id": request_id,
                "decided_by": "gate",
            },
        )

    for entry in sorted(entries, key=lambda e: e.get("ts", 0), reverse=True):
        route = entry.get("route") or {}
        if (
            entry.get("tool") in ROUTING_TOOLS
            and route.get("agent") == agent
            and entry.get("action") not in ("VERIFY", "BLOCKED")
            and entry.get("request_id") not in used
        ):
            used.add(entry.get("request_id"))
            with contextlib.suppress(OSError):
                state.write_text(json.dumps(sorted(u for u in used if u)))
            log("ALLOWED", entry.get("request_id"))
            return True, ""

    if any(e.get("error") == "JEV_UNAVAILABLE" and e.get("ts", 0) >= now - DEGRADED_WINDOW_SECONDS for e in entries):
        log("ALLOWED_DEGRADED")
        return True, ""

    routed = sorted(
        {
            (e.get("route") or {}).get("agent")
            for e in entries
            if e.get("tool") in ROUTING_TOOLS and e.get("request_id") not in used
        }
        - {None}
    )
    hint = f" Unused decisions in this session route to: {', '.join(routed)}." if routed else ""
    log("BLOCKED_DISPATCH")
    return False, (
        f"Router gate: dispatching '{agent}' needs a routing decision for this unit, and none is available.{hint}\n"
        f'1. If the jev tools are not loaded, load them with ToolSearch query "{LOAD_JEV}".\n'
        f'2. Call mcp__jev__classify_task for this work unit with task_id "{session}:<unit>" '
        f"(use decide_escalation to change lanes, or record_override only when the user explicitly named a lane).\n"
        f"3. Dispatch exactly the agent in the returned route. Each decision allows one dispatch.\n"
        f"If jev returns JEV_UNAVAILABLE, the gate will allow dispatches using local routing rules."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0  # never block on a malformed hook payload
    try:
        policy = Policy.load()
    except (OSError, ValueError, KeyError):
        return 0
    ledger = retention.ledger_path()
    retention.prune_files(ledger.parent, "gate-*.json", retention.cutoff_for(policy.retention_hours))
    allowed, message = evaluate(event, policy, ledger, dict(os.environ))
    if not allowed:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
