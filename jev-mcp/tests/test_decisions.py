import json

import pytest

from jev_router.decisions import Decider, run
from jev_router.jev import ChoiceAnswer, JevError
from jev_router.policy import Policy, hard_gates
from jev_router.schemas import ClassifyRequest, CompletionRequest, EscalationRequest, Evidence, ProgressRequest

LADDER = ["OPUS_LOW", "OPUS_MEDIUM", "OPUS_HIGH", "FABLE_HIGH", "FABLE_XHIGH"]
ID = {"schema_version": "1.0", "request_id": "r1", "task_id": "t1", "policy_version": Policy.load().version}


class FakeJev:
    def __init__(self, choice="SMALL", confidence=0.95, error=None):
        self.choice_value, self.confidence, self.error = choice, confidence, error
        self.calls = []

    def choice(self, state, instructions, options):
        self.calls.append(options)
        if self.error:
            raise self.error
        assert self.choice_value in options, f"{self.choice_value} not offered: {list(options)}"
        return ChoiceAnswer(self.choice_value, self.confidence, {})


def decider(jev, tmp_path):
    return Decider(Policy.load(), jev, ledger_path=tmp_path / "ledger.jsonl")


def evidence(**over):
    base = {
        "fingerprint": "wsfp-1",
        "checks": [{"name": "tests", "status": "PASS", "exit_code": 0}],
        "criteria": [{"id": "A1", "status": "SATISFIED", "evidence_ref": "tests"}],
        "scope_ok": True,
        "known_failures": [],
        "diff_summary": "x",
    }
    base.update(over)
    return base


FAILING = evidence(
    checks=[{"name": "tests", "status": "FAIL", "exit_code": 1}],
    criteria=[{"id": "A1", "status": "UNSATISFIED", "evidence_ref": "log"}],
    known_failures=["3 failing"],
)


# ---- classify ------------------------------------------------------------


def test_classify_maps_class_to_lane_and_echoes_identity(tmp_path):
    d = decider(FakeJev("SMALL", 0.9), tmp_path)
    out = run(ClassifyRequest, d.classify, {**ID, "task": "fix flag", "available_lanes": LADDER})
    assert out["class"] == "SMALL"
    assert out["route"] == {"lane": "OPUS_LOW", "model": "claude-opus-5-5", "effort": "low", "agent": "implement-small"}
    assert out["request_id"] == "r1" and out["evidence_fingerprint"] is None
    assert json.loads((tmp_path / "ledger.jsonl").read_text())["class"] == "SMALL"


def test_classify_low_confidence_raises_class(tmp_path):
    out = run(
        ClassifyRequest,
        decider(FakeJev("SMALL", 0.5), tmp_path).classify,
        {**ID, "task": "x", "available_lanes": LADDER},
    )
    assert out["class"] == "MEDIUM" and out["route"]["lane"] == "OPUS_MEDIUM"


def test_classify_security_floor(tmp_path):
    out = run(
        ClassifyRequest,
        decider(FakeJev("SMALL", 0.99), tmp_path).classify,
        {**ID, "task": "auth", "available_lanes": LADDER, "signals": {"security_sensitive": True}},
    )
    assert out["class"] == "HIGH" and out["route"]["lane"] == "OPUS_HIGH"


def test_classify_never_routes_to_top_lane(tmp_path):
    out = run(
        ClassifyRequest,
        decider(FakeJev("ESCALATE", 0.99), tmp_path).classify,
        {**ID, "task": "x", "available_lanes": ["OPUS_HIGH", "FABLE_XHIGH"]},
    )
    assert out["route"]["lane"] == "OPUS_HIGH"


def test_classify_rejects_unknown_lane_and_fields_and_policy(tmp_path):
    d = decider(FakeJev(), tmp_path)
    assert (
        run(ClassifyRequest, d.classify, {**ID, "task": "x", "available_lanes": ["GPT"]})["error"] == "INVALID_REQUEST"
    )
    assert (
        run(ClassifyRequest, d.classify, {**ID, "task": "x", "available_lanes": LADDER, "extra": 1})["error"]
        == "INVALID_REQUEST"
    )
    stale = {**ID, "policy_version": "0.9"}
    assert (
        run(ClassifyRequest, d.classify, {**stale, "task": "x", "available_lanes": LADDER})["error"]
        == "INVALID_REQUEST"
    )


def test_oversized_input_rejected_not_truncated(tmp_path):
    out = run(
        ClassifyRequest, decider(FakeJev(), tmp_path).classify, {**ID, "task": "x" * 2001, "available_lanes": LADDER}
    )
    assert out["error"] == "INVALID_REQUEST"
    # Every field within its own limit, but the serialized total exceeds 16 KiB.
    big = {
        **ID,
        "task": "t" * 2000,
        "available_lanes": LADDER,
        "acceptance_criteria": ["y" * 500] * 20,
        "signals": {f"{i:02d}" + "k" * 48: "z" * 200 for i in range(20)},
    }
    assert run(ClassifyRequest, decider(FakeJev(), tmp_path).classify, big)["error"] == "INVALID_REQUEST"


def test_jev_unavailable_is_error_not_decision(tmp_path):
    d = decider(FakeJev(error=JevError("JEV_UNAVAILABLE", "down")), tmp_path)
    out = run(CompletionRequest, d.completion, {**ID, "residual_question": "done?", "evidence": evidence()})
    assert out["error"] == "JEV_UNAVAILABLE" and "action" not in out


# ---- progress ------------------------------------------------------------


def test_progress_never_completes_on_failed_gates_even_with_high_confidence(tmp_path):
    jev = FakeJev("ESCALATE", 0.99)
    out = run(
        ProgressRequest,
        decider(jev, tmp_path).progress,
        {**ID, "current_lane": "OPUS_MEDIUM", "attempt": 1, "evidence": FAILING},
    )
    assert "COMPLETE" not in jev.calls[0]
    assert out["action"] == "ESCALATE" and out["evidence_fingerprint"] == "wsfp-1"


@pytest.mark.parametrize("status", ["NOT_RUN", "ERROR"])
def test_progress_unrun_checks_force_verify_without_jev(tmp_path, status):
    jev = FakeJev()
    ev = evidence(
        checks=[
            {"name": "tests", "status": "PASS", "exit_code": 0},
            {"name": "types", "status": status, "exit_code": None},
        ]
    )
    out = run(
        ProgressRequest,
        decider(jev, tmp_path).progress,
        {**ID, "current_lane": "OPUS_LOW", "attempt": 1, "evidence": ev},
    )
    assert out["action"] == "VERIFY" and out["decided_by"] == "local_rule" and not jev.calls


def test_progress_escalates_after_lane_failure_budget(tmp_path):
    jev = FakeJev()
    out = run(
        ProgressRequest,
        decider(jev, tmp_path).progress,
        {**ID, "current_lane": "OPUS_LOW", "attempt": 2, "evidence": FAILING},
    )
    assert out["action"] == "ESCALATE" and not jev.calls


def test_progress_blocks_after_unit_budget(tmp_path):
    out = run(
        ProgressRequest,
        decider(FakeJev(), tmp_path).progress,
        {**ID, "current_lane": "OPUS_HIGH", "attempt": 7, "evidence": FAILING},
    )
    assert out["action"] == "BLOCKED"


def test_progress_low_confidence_becomes_verify(tmp_path):
    out = run(
        ProgressRequest,
        decider(FakeJev("RETRY", 0.4), tmp_path).progress,
        {**ID, "current_lane": "OPUS_LOW", "attempt": 1, "evidence": FAILING},
    )
    assert out["action"] == "VERIFY"


# ---- escalation ----------------------------------------------------------


def test_escalation_route_computed_from_ladder(tmp_path):
    out = run(
        EscalationRequest,
        decider(FakeJev("ESCALATE", 0.9), tmp_path).escalation,
        {
            **ID,
            "current_lane": "OPUS_HIGH",
            "direction": "up",
            "attempt": 2,
            "evidence": FAILING,
            "available_lanes": ["OPUS_HIGH", "FABLE_HIGH", "FABLE_XHIGH"],
        },
    )
    assert out["action"] == "ESCALATE"
    assert out["route"] == {
        "lane": "FABLE_HIGH",
        "model": "claude-fable-5-1",
        "effort": "high",
        "agent": "implement-escalated",
    }


def test_escalation_without_higher_lane_is_blocked(tmp_path):
    out = run(
        EscalationRequest,
        decider(FakeJev("ESCALATE", 0.9), tmp_path).escalation,
        {
            **ID,
            "current_lane": "FABLE_HIGH",
            "direction": "up",
            "attempt": 2,
            "evidence": FAILING,
            "available_lanes": ["OPUS_HIGH", "FABLE_HIGH"],
        },
    )
    assert out["action"] == "BLOCKED" and out["route"]["lane"] == "FABLE_HIGH"


def test_deescalation_and_direction_limits_options(tmp_path):
    jev = FakeJev("DEESCALATE", 0.9)
    out = run(
        EscalationRequest,
        decider(jev, tmp_path).escalation,
        {
            **ID,
            "current_lane": "FABLE_HIGH",
            "direction": "down",
            "attempt": 1,
            "evidence": evidence(),
            "available_lanes": LADDER,
        },
    )
    assert set(jev.calls[0]) == {"KEEP", "DEESCALATE", "VERIFY"}
    assert out["route"]["lane"] == "OPUS_HIGH"


def test_keep_and_verify_keep_current_route(tmp_path):
    out = run(
        EscalationRequest,
        decider(FakeJev("KEEP", 0.9), tmp_path).escalation,
        {
            **ID,
            "current_lane": "OPUS_MEDIUM",
            "direction": "reassess",
            "attempt": 1,
            "evidence": FAILING,
            "available_lanes": LADDER,
        },
    )
    assert out["route"]["lane"] == "OPUS_MEDIUM"


# ---- completion ----------------------------------------------------------


def test_completion_requires_gates(tmp_path):
    jev = FakeJev("COMPLETE", 0.99)
    out = run(
        CompletionRequest, decider(jev, tmp_path).completion, {**ID, "residual_question": "done?", "evidence": FAILING}
    )
    assert out["action"] == "CONTINUE" and not jev.calls


def test_completion_passes_with_confident_jev(tmp_path):
    out = run(
        CompletionRequest,
        decider(FakeJev("COMPLETE", 0.94), tmp_path).completion,
        {**ID, "residual_question": "done?", "evidence": evidence()},
    )
    assert out["action"] == "COMPLETE" and out["evidence_fingerprint"] == "wsfp-1"


def test_completion_low_confidence_is_verify(tmp_path):
    out = run(
        CompletionRequest,
        decider(FakeJev("COMPLETE", 0.6), tmp_path).completion,
        {**ID, "residual_question": "done?", "evidence": evidence()},
    )
    assert out["action"] == "VERIFY"


# ---- schema consistency --------------------------------------------------


@pytest.mark.parametrize(
    "check",
    [
        {"name": "t", "status": "PASS", "exit_code": 1},
        {"name": "t", "status": "PASS", "exit_code": None},
        {"name": "t", "status": "NOT_RUN", "exit_code": 0},
        {"name": "t", "status": "FAIL", "exit_code": 0},
    ],
)
def test_inconsistent_checks_rejected(check):
    with pytest.raises(ValueError):
        Evidence.model_validate(evidence(checks=[check]))


def test_gate_requires_passing_check_and_criteria():
    assert not hard_gates(Evidence.model_validate(evidence(checks=[]))).passed
    assert not hard_gates(Evidence.model_validate(evidence(criteria=[]))).passed
    assert not hard_gates(Evidence.model_validate(evidence(scope_ok=False))).passed
    assert hard_gates(Evidence.model_validate(evidence())).passed
