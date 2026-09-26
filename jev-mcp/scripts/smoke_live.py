"""Live smoke test: start the stdio MCP server, call the real Jev API, assert the invariants.

Usage: uv run python scripts/smoke_live.py <path-to-jev-router-mcp>
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ID = {"schema_version": "1.0", "task_id": "smoke", "policy_version": "1.0"}
LADDER = ["SONNET_MEDIUM", "OPUS_MEDIUM", "OPUS_HIGH", "FABLE_HIGH", "FABLE_XHIGH"]
EXPECTED_TOOLS = {
    "get_policy",
    "classify_task",
    "assess_progress",
    "decide_escalation",
    "assess_completion",
    "record_override",
}

TASKS = [
    # (task, signals, lanes the result may land in)
    ("Fix a typo in a README heading", {}, {"SONNET_MEDIUM"}),
    ("Add pagination to an existing REST list endpoint with tests", {}, {"OPUS_MEDIUM", "OPUS_HIGH"}),
    (
        "Debug an intermittent race condition between Redis stream workers and the SSE publisher",
        {},
        {"OPUS_HIGH", "FABLE_HIGH"},
    ),
    ("Rotate session tokens on password change", {"security_sensitive": True}, {"OPUS_HIGH", "FABLE_HIGH"}),
]

FAILING = {
    "fingerprint": "wsfp-smoke",
    "checks": [{"name": "tests", "status": "FAIL", "exit_code": 1}],
    "criteria": [{"id": "A1", "status": "UNSATISFIED", "evidence_ref": "tests.log"}],
    "scope_ok": True,
    "known_failures": ["1 failing test"],
    "diff_summary": "validation changed",
}


async def call(session, tool, args):
    res = await session.call_tool(tool, args)
    return json.loads(res.content[0].text)


async def main(server: str) -> int:
    failures = []
    # Keep smoke-test decisions out of the real decision log.
    ledger = Path(tempfile.mkdtemp(prefix="router-smoke-")) / "decisions.jsonl"
    params = StdioServerParameters(command=server, args=[], env={**os.environ, "ROUTER_LEDGER": str(ledger)})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        ID["policy_version"] = (await call(s, "get_policy", {}))["policy_version"]
        tools = {t.name for t in (await s.list_tools()).tools}
        print("tools:", sorted(tools))
        if tools != EXPECTED_TOOLS:
            failures.append(f"unexpected tool set: {sorted(tools)}")

        for i, (task, signals, allowed) in enumerate(TASKS):
            args = {**ID, "request_id": f"c{i}", "task": task, "available_lanes": LADDER, "signals": signals}
            out = await call(s, "classify_task", args)
            lane = out.get("route", {}).get("lane")
            print(f"  {out.get('class')!s:9} {lane!s:12} conf={out.get('confidence')} | {task}")
            if "error" in out:
                failures.append(f"classify error: {out}")
            elif lane not in allowed:
                failures.append(f"{task!r} routed to {lane}, expected one of {sorted(allowed)}")
            elif out["request_id"] != f"c{i}":
                failures.append("classify did not echo request_id")

        out = await call(
            s, "assess_completion", {**ID, "request_id": "done", "residual_question": "Done?", "evidence": FAILING}
        )
        print("  completion with failing tests ->", out.get("action"))
        if out.get("action") == "COMPLETE":
            failures.append("COMPLETE returned while hard gates fail")

        out = await call(
            s,
            "assess_progress",
            {**ID, "request_id": "p1", "current_lane": "OPUS_MEDIUM", "attempt": 1, "evidence": FAILING},
        )
        print("  progress after failed attempt ->", out.get("action"), f"({out.get('decided_by')})")
        if out.get("action") not in {"CONTINUE", "RETRY", "VERIFY", "ESCALATE"}:
            failures.append(f"unexpected progress action: {out}")
        if out.get("evidence_fingerprint") != "wsfp-smoke":
            failures.append("progress did not echo the evidence fingerprint")

    for f in failures:
        print("FAIL:", f)
    print("smoke test", "FAILED" if failures else "passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1])))
