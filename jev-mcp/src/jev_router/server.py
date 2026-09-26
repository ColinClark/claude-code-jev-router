"""MCP server `jev`: four bounded decision tools. No shell, no file access, no code writing."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from mcp.server.mcpserver import MCPServer

from .decisions import Decider, run
from .jev import JevClient
from .policy import Policy
from .schemas import (
    ClassifyRequest,
    CompletionRequest,
    EscalationRequest,
    Evidence,
    OverrideRequest,
    ProgressRequest,
)

mcp = MCPServer(
    "jev",
    instructions=(
        "Advisory routing decisions for the engineering orchestrator. Call only for residual judgment that "
        "deterministic tools cannot establish. Reject any reply whose request_id, task_id, policy_version or "
        "evidence_fingerprint does not match your request. A reply with an `error` field is never a decision."
    ),
)


@lru_cache(maxsize=1)
def decider() -> Decider:
    policy = Policy.load()
    jev = policy.jev
    client = JevClient(
        endpoint=jev.get("endpoint", "https://api.typesafe.ai/v1/systemone"),
        model=jev.get("model", "jev-latest"),
        timeout_seconds=float(jev.get("timeout_seconds", 10)),
        env_file=jev.get("env_file", "~/.config/jev/.env"),
    )
    return Decider(policy, client)


@mcp.tool()
def get_policy() -> dict:
    """Return the deployed policy version, lanes (agent/model/effort), ladder and limits."""
    p = decider().policy
    return {
        "policy_version": p.version,
        "lanes": {name: p.route(name) for name in p.lanes},
        "ladder": p.ladder,
        "classes": {name: spec["lane"] for name, spec in p.classes.items()},
        "limits": {
            "confidence_threshold": p.confidence_threshold,
            "max_failed_cycles_per_lane": p.max_failed_cycles_per_lane,
            "max_cycles_per_unit": p.max_cycles_per_unit,
        },
    }


@mcp.tool()
def classify_task(
    schema_version: Literal["1.0"],
    request_id: str,
    task_id: str,
    policy_version: str,
    task: str,
    available_lanes: list[str],
    acceptance_criteria: list[str] | None = None,
    signals: dict[str, str | bool | int | float] | None = None,
) -> dict:
    """Classify a bounded work unit as SMALL/MEDIUM/HIGH/ESCALATE and return the policy route.

    Use only when classification needs judgment. signals may include e.g. scope, pattern_known,
    security_sensitive (true forces at least HIGH). Never routes to the top lane directly.
    """
    payload = dict(
        schema_version=schema_version,
        request_id=request_id,
        task_id=task_id,
        policy_version=policy_version,
        task=task,
        available_lanes=available_lanes,
        acceptance_criteria=acceptance_criteria or [],
        signals=signals or {},
    )
    return run(ClassifyRequest, decider().classify, payload)


@mcp.tool()
def assess_progress(
    schema_version: Literal["1.0"],
    request_id: str,
    task_id: str,
    policy_version: str,
    current_lane: str,
    attempt: int,
    evidence: Evidence,
) -> dict:
    """After a worker cycle: CONTINUE, RETRY, VERIFY, ESCALATE, COMPLETE or BLOCKED.

    Hard gates are evaluated locally first; COMPLETE is impossible while any check or criterion fails.
    """
    payload = dict(
        schema_version=schema_version,
        request_id=request_id,
        task_id=task_id,
        policy_version=policy_version,
        current_lane=current_lane,
        attempt=attempt,
        evidence=evidence.model_dump(mode="json"),
    )
    return run(ProgressRequest, decider().progress, payload)


@mcp.tool()
def decide_escalation(
    schema_version: Literal["1.0"],
    request_id: str,
    task_id: str,
    policy_version: str,
    current_lane: str,
    direction: Literal["up", "down", "reassess"],
    attempt: int,
    evidence: Evidence,
    available_lanes: list[str],
) -> dict:
    """KEEP, ESCALATE, DEESCALATE or VERIFY, with the resulting route computed from the policy ladder.

    Include FABLE_XHIGH in available_lanes only when an extreme escalation is explicitly budgeted.
    Returns BLOCKED if escalation is warranted but no higher lane is available.
    """
    payload = dict(
        schema_version=schema_version,
        request_id=request_id,
        task_id=task_id,
        policy_version=policy_version,
        current_lane=current_lane,
        direction=direction,
        attempt=attempt,
        evidence=evidence.model_dump(mode="json"),
        available_lanes=available_lanes,
    )
    return run(EscalationRequest, decider().escalation, payload)


@mcp.tool()
def assess_completion(
    schema_version: Literal["1.0"],
    request_id: str,
    task_id: str,
    policy_version: str,
    residual_question: str,
    evidence: Evidence,
) -> dict:
    """COMPLETE, VERIFY or CONTINUE for a residual acceptance question once hard gates pass.

    Skip this tool when no residual judgment remains; the local completion gate is sufficient.
    """
    payload = dict(
        schema_version=schema_version,
        request_id=request_id,
        task_id=task_id,
        policy_version=policy_version,
        residual_question=residual_question,
        evidence=evidence.model_dump(mode="json"),
    )
    return run(CompletionRequest, decider().completion, payload)


@mcp.tool()
def record_override(
    schema_version: Literal["1.0"],
    request_id: str,
    task_id: str,
    policy_version: str,
    lane: str,
    reason: str,
) -> dict:
    """Record a lane the USER explicitly asked for (e.g. "use implement-high for this"), so it may be dispatched.

    Only for explicit user instructions; never to bypass a classification you disagree with. Logged and shown
    in /router-report as a user override.
    """
    payload = dict(
        schema_version=schema_version,
        request_id=request_id,
        task_id=task_id,
        policy_version=policy_version,
        lane=lane,
        reason=reason,
    )
    return run(OverrideRequest, decider().override, payload)


def main() -> None:
    # Request lines add noise to Claude Code's MCP logs; keep only warnings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
