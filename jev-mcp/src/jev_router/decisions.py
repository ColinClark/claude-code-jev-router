"""Decision engine: local hard rules first, Jev only for residual judgment.

Every response echoes the request identity and evidence fingerprint so the
orchestrator can reject stale or mismatched decisions. Routes are always
computed here from the policy ladder; Jev only picks an action or class.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .jev import JevClient, JevError
from .policy import CLASS_ORDER, Policy, PolicyError, floor_class, hard_gates, raise_class
from .schemas import ClassifyRequest, CompletionRequest, EscalationRequest, Identity, ProgressRequest

MAX_REASON = 600

CLASSIFY_INSTRUCTIONS = (
    "Classify the engineering complexity of this bounded work unit so it can be routed to a coding model. "
    "Choose the lowest class that can reliably complete it with verification."
)
PROGRESS_INSTRUCTIONS = (
    "A coding agent attempted this work unit. Deterministic checks have already been run; their results are facts. "
    "Choose the next action for the orchestrator."
)
ESCALATION_INSTRUCTIONS = (
    "Decide whether this work unit should stay on its current model lane, move to a stronger or cheaper lane, "
    "or collect more evidence first. Change lanes only when the evidence justifies it."
)
COMPLETION_INSTRUCTIONS = (
    "All deterministic checks and acceptance criteria pass. Judge only the residual question: is the task "
    "genuinely complete and within scope?"
)

ACTION_TEXT = {
    "CONTINUE": "Useful progress was made; move on to the next bounded unit.",
    "RETRY": "Retry the same unit on the same lane with a new hypothesis; the failure looks recoverable.",
    "VERIFY": "Evidence is missing, stale or inconclusive; collect more evidence before editing further.",
    "ESCALATE": "The problem was adequately investigated but exceeds the current lane; use more capability.",
    "COMPLETE": "The work is done: behavior implemented, in scope, and no open acceptance question.",
    "KEEP": "Stay on the current lane.",
    "DEESCALATE": "The hard part is resolved; the remaining work is routine and fits a cheaper lane.",
}


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return bool(value)


class Decider:
    def __init__(self, policy: Policy, jev: JevClient, ledger_path: str | os.PathLike | None = None):
        self.policy = policy
        self.jev = jev
        default_ledger = Path("~/.local/state/claude-router/decisions.jsonl").expanduser()
        self.ledger_path = Path(ledger_path or os.environ.get("ROUTER_LEDGER") or default_ledger)

    # ---- tools -----------------------------------------------------------

    def classify(self, req: ClassifyRequest) -> dict:
        self._check_policy(req)
        lanes = self.policy.check_ladder_lanes(req.available_lanes)
        # The top lane (FABLE_XHIGH) needs an explicit escalation decision, never a first classification.
        candidates = [lane for lane in lanes if lane != self.policy.ladder[-1]] or lanes
        options = {name: spec["description"] for name, spec in self.policy.classes.items()}
        state = {"task": req.task, "acceptance_criteria": req.acceptance_criteria, "signals": req.signals}
        answer = self.jev.choice(state, CLASSIFY_INSTRUCTIONS, options)

        cls, notes = answer.choice, [f"Jev chose {answer.choice} ({answer.confidence:.2f})."]
        if answer.confidence < self.policy.confidence_threshold:
            # Hedge toward the stronger of Jev's top two candidates; blind +1 only without probabilities.
            top_two = sorted(answer.probabilities, key=answer.probabilities.get, reverse=True)[:2]
            if len(top_two) == 2 and answer.choice in top_two:
                cls = max(top_two, key=CLASS_ORDER.index)
            else:
                cls = raise_class(cls)
            notes.append(f"Below threshold {self.policy.confidence_threshold:.2f}; hedged to {cls}.")
        if _truthy(req.signals.get("security_sensitive")):
            floored = floor_class(cls, self.policy.security_min_class)
            if floored != cls:
                notes.append(f"Security-sensitive; raised to {floored}.")
            cls = floored
        lane = self.policy.lane_for_class(cls, candidates)
        return self._result(
            req, None, "jev", answer.confidence, " ".join(notes), **{"class": cls, "route": self.policy.route(lane)}
        )

    def progress(self, req: ProgressRequest) -> dict:
        self._check_policy(req)
        self._check_lane(req.current_lane)
        fp, gate = req.evidence.fingerprint, hard_gates(req.evidence)
        limits = self.policy

        if req.attempt > limits.max_cycles_per_unit:
            return self._local(
                req,
                fp,
                "BLOCKED",
                f"Cycle budget exhausted ({req.attempt} > {limits.max_cycles_per_unit}); "
                "reassess scope or budget with the user.",
            )
        if gate.needs_verify:
            return self._local(req, fp, "VERIFY", "Evidence incomplete: " + "; ".join(gate.reasons))
        if gate.passed:
            allowed = ["CONTINUE", "COMPLETE", "VERIFY"]
        elif req.attempt >= limits.max_failed_cycles_per_lane:
            return self._local(
                req,
                fp,
                "ESCALATE",
                f"{req.attempt} unsuccessful cycles on {req.current_lane}: " + "; ".join(gate.reasons),
            )
        else:
            allowed = ["CONTINUE", "RETRY", "VERIFY", "ESCALATE"]

        state = {
            "current_lane": req.current_lane,
            "attempt": req.attempt,
            "hard_gate_failures": gate.reasons,
            "evidence": req.evidence.model_dump(mode="json"),
        }
        answer = self.jev.choice(state, PROGRESS_INSTRUCTIONS, {a: ACTION_TEXT[a] for a in allowed})
        action, reason = self._thresholded(answer)
        if action == "COMPLETE" and not gate.passed:  # defensive; COMPLETE is only offered when gates pass
            action, reason = "VERIFY", "Rejected COMPLETE: hard gates did not pass."
        return self._result(req, fp, "jev", answer.confidence, reason, action=action)

    def escalation(self, req: EscalationRequest) -> dict:
        self._check_policy(req)
        self._check_lane(req.current_lane)
        lanes = self.policy.check_ladder_lanes(req.available_lanes)
        fp = req.evidence.fingerprint
        allowed = {
            "up": ["KEEP", "ESCALATE", "VERIFY"],
            "down": ["KEEP", "DEESCALATE", "VERIFY"],
            "reassess": ["KEEP", "ESCALATE", "DEESCALATE", "VERIFY"],
        }[req.direction]
        state = {
            "current_lane": req.current_lane,
            "direction": req.direction,
            "attempt": req.attempt,
            "ladder": lanes,
            "hard_gate_failures": hard_gates(req.evidence).reasons,
            "evidence": req.evidence.model_dump(mode="json"),
        }
        answer = self.jev.choice(state, ESCALATION_INSTRUCTIONS, {a: ACTION_TEXT[a] for a in allowed})
        action, reason = self._thresholded(answer)

        lane = req.current_lane
        if action == "ESCALATE":
            nxt = self.policy.next_up(lane, lanes)
            if nxt is None:
                action, reason = "BLOCKED", f"Escalation chosen but no lane above {lane} is available. {reason}"
            else:
                lane = nxt
        elif action == "DEESCALATE":
            nxt = self.policy.next_down(lane, lanes)
            if nxt is None:
                action, reason = "KEEP", f"No cheaper lane than {lane} is available. {reason}"
            else:
                lane = nxt
        return self._result(req, fp, "jev", answer.confidence, reason, action=action, route=self.policy.route(lane))

    def completion(self, req: CompletionRequest) -> dict:
        self._check_policy(req)
        fp, gate = req.evidence.fingerprint, hard_gates(req.evidence)
        if not gate.passed:
            action = "VERIFY" if gate.needs_verify else "CONTINUE"
            return self._local(req, fp, action, "Hard gates not met: " + "; ".join(gate.reasons))
        state = {"residual_question": req.residual_question, "evidence": req.evidence.model_dump(mode="json")}
        options = {a: ACTION_TEXT[a] for a in ("COMPLETE", "VERIFY", "CONTINUE")}
        answer = self.jev.choice(state, COMPLETION_INSTRUCTIONS, options)
        action, reason = self._thresholded(answer)
        return self._result(req, fp, "jev", answer.confidence, reason, action=action)

    # ---- helpers ---------------------------------------------------------

    def _thresholded(self, answer) -> tuple[str, str]:
        reason = f"Jev chose {answer.choice} ({answer.confidence:.2f})."
        if answer.confidence < self.policy.confidence_threshold and answer.choice != "VERIFY":
            return (
                "VERIFY",
                reason + f" Below threshold {self.policy.confidence_threshold:.2f}; collect targeted evidence first.",
            )
        return answer.choice, reason

    def _check_policy(self, req: Identity) -> None:
        if req.policy_version != self.policy.version:
            raise PolicyError(f"policy_version {req.policy_version!r} does not match deployed {self.policy.version!r}")

    def _check_lane(self, lane: str) -> None:
        if lane not in self.policy.ladder:
            raise PolicyError(f"current_lane {lane!r} is not an implementation lane")

    def _local(self, req, fp, action: str, reason: str) -> dict:
        return self._result(req, fp, "local_rule", 1.0, reason, action=action)

    def _result(self, req: Identity, fp: str | None, decided_by: str, confidence: float, reason: str, **fields) -> dict:
        result = {
            "schema_version": req.schema_version,
            "request_id": req.request_id,
            "task_id": req.task_id,
            "policy_version": req.policy_version,
            "evidence_fingerprint": fp,
            **fields,
            "confidence": round(float(confidence), 4),
            "reason": reason[:MAX_REASON],
            "decided_by": decided_by,
        }
        self._record(result)
        return result

    def _record(self, result: dict) -> None:
        """Append a sanitized decision record (no task text, no evidence body) for later tuning."""
        entry = {
            k: result.get(k)
            for k in (
                "request_id",
                "task_id",
                "policy_version",
                "evidence_fingerprint",
                "action",
                "class",
                "route",
                "confidence",
                "decided_by",
            )
        }
        entry["ts"] = time.time()
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass


def error_result(payload: dict, code: str, reason: str) -> dict:
    """Error reply; never carries an action, so it can never be read as COMPLETE."""
    return {
        "error": code,
        "schema_version": payload.get("schema_version"),
        "request_id": payload.get("request_id"),
        "task_id": payload.get("task_id"),
        "policy_version": payload.get("policy_version"),
        "reason": str(reason)[:MAX_REASON],
    }


def run(model_cls, handler, payload: dict) -> dict:
    from pydantic import ValidationError

    try:
        req = model_cls.model_validate(payload)
    except ValidationError as exc:
        msgs = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False)[:5]]
        return error_result(payload, "INVALID_REQUEST", "; ".join(msgs))
    try:
        return handler(req)
    except PolicyError as exc:
        return error_result(payload, "INVALID_REQUEST", str(exc))
    except JevError as exc:
        return error_result(payload, exc.code, exc.message)
