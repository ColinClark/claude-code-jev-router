import json

import pytest

from jev_router import gate, retention
from jev_router.decisions import Decider, run
from jev_router.jev import ChoiceAnswer, JevError
from jev_router.policy import Policy
from jev_router.schemas import ClassifyRequest, EscalationRequest, OverrideRequest

SESSION = "sess-123"
LADDER = ["OPUS_LOW", "OPUS_MEDIUM", "OPUS_HIGH", "FABLE_HIGH", "FABLE_XHIGH"]


class FakeJev:
    def __init__(self, choice="SMALL", confidence=0.95, error=None):
        self.choice_value, self.confidence, self.error = choice, confidence, error

    def choice(self, state, instructions, options):
        if self.error:
            raise self.error
        return ChoiceAnswer(self.choice_value, self.confidence, {})


@pytest.fixture
def env(tmp_path):
    return {"ledger": tmp_path / "decisions.jsonl", "env": {"CLAUDE_PROJECT_DIR": str(tmp_path / "proj")}}


def ident(n, session=SESSION):
    policy = Policy.load()
    return {
        "schema_version": "1.0",
        "request_id": f"r{n}",
        "task_id": f"{session}:unit-{n}",
        "policy_version": policy.version,
    }


def classify(ledger, n, choice="SMALL", session=SESSION, error=None):
    d = Decider(Policy.load(), FakeJev(choice, error=error), ledger_path=ledger)
    return run(ClassifyRequest, d.classify, {**ident(n, session), "task": "t", "available_lanes": LADDER})


def dispatch(env, agent, session=SESSION):
    event = {"session_id": session, "tool_name": "Agent", "tool_input": {"subagent_type": agent}}
    return gate.evaluate(event, Policy.load(), env["ledger"], env["env"])


def test_ungated_agents_always_allowed(env):
    for agent in ("lookup", "research", "Explore", "general-purpose", None):
        assert dispatch(env, agent) == (True, "")


def test_blocks_without_decision_and_explains(env):
    allowed, message = dispatch(env, "implement-medium")
    assert not allowed
    assert "mcp__jev__classify_task" in message and f'"{SESSION}:<unit>"' in message and "ToolSearch" in message
    gate_entries = [e for e in retention.read_entries(env["ledger"]) if e["tool"] == "dispatch_gate"]
    assert gate_entries[-1]["action"] == "BLOCKED_DISPATCH"


def test_decision_allows_exactly_its_agent_once(env):
    classify(env["ledger"], 1, "MEDIUM")
    assert dispatch(env, "implement-small")[0] is False  # wrong lane for the decision
    assert dispatch(env, "implement-medium") == (True, "")
    assert dispatch(env, "implement-medium")[0] is False  # decision already used
    classify(env["ledger"], 2, "MEDIUM")
    assert dispatch(env, "implement-medium") == (True, "")


def test_other_sessions_decisions_do_not_count(env):
    classify(env["ledger"], 1, "SMALL", session="someone-else")
    allowed, _ = dispatch(env, "implement-small")
    assert not allowed


def test_block_message_names_available_routes(env):
    classify(env["ledger"], 1, "HIGH")
    allowed, message = dispatch(env, "implement-small")
    assert not allowed and "implement-medium" in message  # HIGH is capped at OPUS_MEDIUM for a first attempt


def test_escalation_and_override_routes_are_accepted(env):
    policy = Policy.load()
    d = Decider(policy, FakeJev("ESCALATE", 0.9), ledger_path=env["ledger"])
    evidence = {
        "fingerprint": "wsfp-1",
        "checks": [{"name": "t", "status": "FAIL", "exit_code": 1}],
        "criteria": [{"id": "A1", "status": "UNSATISFIED", "evidence_ref": "x"}],
        "scope_ok": True,
    }
    out = run(
        EscalationRequest,
        d.escalation,
        {
            **ident(3),
            "current_lane": "OPUS_MEDIUM",
            "direction": "up",
            "attempt": 2,
            "evidence": evidence,
            "available_lanes": LADDER,
        },
    )
    assert out["route"]["agent"] == "implement-high"
    assert dispatch(env, "implement-high") == (True, "")

    out = run(OverrideRequest, d.override, {**ident(4), "lane": "FABLE_HIGH", "reason": "user: use Fable for this"})
    assert out["action"] == "OVERRIDE" and out["decided_by"] == "user_override"
    assert dispatch(env, "implement-escalated") == (True, "")


def test_jev_unavailable_opens_degraded_mode(env):
    out = classify(env["ledger"], 5, error=JevError("JEV_UNAVAILABLE", "down"))
    assert out["error"] == "JEV_UNAVAILABLE"
    assert dispatch(env, "implement-medium") == (True, "")
    actions = [e.get("action") for e in retention.read_entries(env["ledger"]) if e.get("tool") == "dispatch_gate"]
    assert actions[-1] == "ALLOWED_DEGRADED"


def test_router_off_disables_gate(env, tmp_path):
    assert dispatch(dict(env, env={"CLAUDE_ROUTER": "off"}), "implement-high") == (True, "")
    marker = tmp_path / "proj" / ".claude" / "router.off"
    marker.parent.mkdir(parents=True)
    marker.touch()
    assert dispatch(env, "implement-high") == (True, "")


def test_main_exit_codes(env, monkeypatch, capsys):
    monkeypatch.setenv("ROUTER_LEDGER", str(env["ledger"]))
    monkeypatch.delenv("CLAUDE_ROUTER", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", env["env"]["CLAUDE_PROJECT_DIR"])
    event = {"session_id": SESSION, "tool_input": {"subagent_type": "implement-small"}}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(event)))
    assert gate.main() == 2
    assert "Router gate" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    assert gate.main() == 0  # never block on a malformed payload


def test_report_summarizes_gate_and_overrides(env):
    from jev_router import usage

    classify(env["ledger"], 1, "SMALL")
    dispatch(env, "implement-small")
    dispatch(env, "implement-high")
    summary = usage.decision_summary(env["ledger"], 0, 9e12, Policy.load())
    assert summary["dispatch_gate"] == {"ALLOWED": 1, "BLOCKED_DISPATCH": 1}
    assert summary["decisions"] == 1 and summary["initial_lanes"] == {"OPUS_LOW": 1}
