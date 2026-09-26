import json
import os
import time
from datetime import UTC, datetime

import pytest

from jev_router import retention, usage
from jev_router.policy import Policy

NOW = time.time() - 60  # anchored to the real clock so the CLI test (which uses time.time()) agrees
HOUR = 3600


def iso(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def assistant(req, model, ts, output, effort="medium", cwd="/work/app", cache_read=0, w5=0, block=0):
    return {
        "type": "assistant",
        "requestId": req,
        "apiBlockIndex": block,
        "timestamp": iso(ts),
        "effort": effort,
        "cwd": cwd,
        "sessionId": "s1",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": output,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": w5,
                "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": 0},
            },
        },
    }


def write_jsonl(path, records, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    proj = root / "-work-app"
    # Main session: one request split over two blocks (must count once, final values), one old request.
    write_jsonl(
        proj / "s1.jsonl",
        [
            {"type": "user", "timestamp": iso(NOW - HOUR)},
            assistant("r1", "claude-opus-5-5", NOW - HOUR, output=5, block=0),
            assistant("r1", "claude-opus-5-5", NOW - HOUR, output=500, block=1, cache_read=2000),
            assistant("r-old", "claude-opus-5-5", NOW - 30 * HOUR, output=999),
            assistant("r-synth", "<synthetic>", NOW - HOUR, output=1),
        ],
    )
    # Router lane subagent on the right model.
    sub = proj / "s1" / "subagents"
    write_jsonl(sub / "agent-a.jsonl", [assistant("r2", "claude-opus-5-5", NOW - 2 * HOUR, output=100, effort="low")])
    (sub / "agent-a.meta.json").write_text(json.dumps({"agentType": "implement-small"}))
    # Router lane subagent on the WRONG model (mismatch), plus an unpriced model elsewhere.
    write_jsonl(sub / "agent-b.jsonl", [assistant("r3", "claude-sonnet-5", NOW - 2 * HOUR, output=50)])
    (sub / "agent-b.meta.json").write_text(json.dumps({"agentType": "implement-high"}))
    write_jsonl(sub / "agent-c.jsonl", [assistant("r4", "mystery-model", NOW - HOUR, output=10)])
    (sub / "agent-c.meta.json").write_text(json.dumps({"agentType": "Explore"}))
    # A file untouched for two days is skipped without being read.
    write_jsonl(
        root / "-other" / "old.jsonl", [assistant("r5", "claude-opus-5-5", NOW - HOUR, output=1)], mtime=NOW - 48 * HOUR
    )
    return root


def test_report_dedupes_filters_prices_and_maps_lanes(projects, tmp_path):
    report = usage.build_report(Policy.load(), 24, now=NOW, root=projects, ledger=tmp_path / "none.jsonl")
    t = report["totals"]
    assert t["requests"] == 4  # r1 once, r2, r3, r4; old, synthetic and stale-file calls excluded
    assert report["by_model"]["claude-opus-5-5"]["output_tokens"] == 600  # r1 final 500 + r2 100
    assert report["by_model"]["claude-opus-5-5"]["cache_read_tokens"] == 2000

    # r1: 1000*4 + 500*20 + 2000*0.2 ; r2: 1000*4 + 100*20   (per million)
    expected_opus = (4000 + 10000 + 400 + 4000 + 2000) / 1e6
    assert report["by_model"]["claude-opus-5-5"]["est_cost_usd"] == pytest.approx(expected_opus, abs=1e-4)
    assert report["by_model"]["mystery-model"]["unpriced_requests"] == 1

    agents = report["by_agent"]
    assert agents["implement-small"]["lane"] == "OPUS_LOW"
    assert agents["implement-small"]["efforts"] == {"low": 1}
    assert agents[usage.MAIN]["lane"] == "—"
    assert agents["Explore"]["lane"] == "not a router lane"
    assert report["lane_model_mismatches"] == [
        {
            "agent": "implement-high",
            "lane": "OPUS_HIGH",
            "expected_model": "claude-opus-5-5",
            "observed": {"claude-sonnet-5": 1},
        }
    ]


def test_window_and_project_filter(projects, tmp_path):
    ledger = tmp_path / "none.jsonl"
    assert usage.build_report(Policy.load(), 1.5, now=NOW, root=projects, ledger=ledger)["totals"]["requests"] == 2
    assert (
        usage.build_report(Policy.load(), 24, project="nomatch", now=NOW, root=projects, ledger=ledger)["totals"][
            "requests"
        ]
        == 0
    )


def test_price_lookup_strips_date_suffix():
    pricing = Policy.load().pricing
    assert usage.price_for("claude-haiku-4-5-20251001", pricing)["input"] == 1.0
    assert usage.price_for("unknown", pricing) is None


def test_decision_summary_prunes_ledger_and_counts(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    entries = [
        {"ts": NOW - 48 * HOUR, "tool": "classify_task", "class": "SMALL", "task_id": "old", "decided_by": "jev"},
        {
            "ts": NOW - HOUR,
            "tool": "classify_task",
            "class": "MEDIUM",
            "route": {"lane": "OPUS_MEDIUM"},
            "task_id": "t1",
            "decided_by": "jev",
            "confidence": 0.9,
        },
        {
            "ts": NOW - HOUR,
            "tool": "assess_progress",
            "action": "ESCALATE",
            "task_id": "t1",
            "decided_by": "local_rule",
            "confidence": 1.0,
        },
    ]
    write_jsonl(ledger, entries)
    summary = usage.decision_summary(ledger, NOW - 24 * HOUR, NOW, Policy.load())
    assert summary["decisions"] == 2 and summary["tasks"] == 1
    assert summary["initial_lanes"] == {"OPUS_MEDIUM": 1}
    assert summary["actions"] == {"ESCALATE": 1}
    assert summary["avg_jev_confidence"] == 0.9  # local-rule confidence excluded
    assert len(ledger.read_text().splitlines()) == 2  # the 48h-old entry was pruned from disk


def test_render_text_and_markdown(projects, tmp_path):
    report = usage.build_report(Policy.load(), 24, now=NOW, root=projects, ledger=tmp_path / "none.jsonl")
    text = usage.render(report)
    assert "By lane / agent" in text and "implement-small" in text and "mismatches" in text
    md = usage.render(report, markdown=True)
    assert md.startswith("## Model usage") and "| model |" in md


def test_prune_helpers(tmp_path):
    ledger = tmp_path / "l.jsonl"
    write_jsonl(ledger, [{"ts": 10}, {"ts": 100}])
    ledger.write_text(ledger.read_text() + "not json\n")
    assert retention.prune_jsonl(ledger, cutoff=50) == 2
    assert [json.loads(line)["ts"] for line in ledger.read_text().splitlines()] == [100]
    assert retention.prune_jsonl(tmp_path / "missing.jsonl", cutoff=50) == 0

    old, new = tmp_path / "ev" / "old", tmp_path / "ev" / "new"
    old.mkdir(parents=True)
    new.mkdir()
    past = time.time() - 48 * HOUR
    os.utime(old, (past, past))
    assert retention.prune_dirs(tmp_path / "ev", retention.cutoff_for(24)) == 1
    assert not old.exists() and new.exists()


def test_cli_json(projects, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(projects.parent))
    monkeypatch.setenv("ROUTER_LEDGER", str(tmp_path / "ledger.jsonl"))
    assert usage.main(["--hours", "1000000", "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["requests"] >= 4


def test_project_name_folds_worktrees_and_home():
    home = str(usage.Path.home())
    assert usage.project_name(f"{home}/Dev/app/.claude/worktrees/feat-x/sub/dir") == "~/Dev/app"
    assert usage.project_name(f"{home}/Dev/app") == "~/Dev/app"
    assert usage.project_name("/srv/app") == "/srv/app"


def test_calls_attributed_to_session_start_project(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(
        root / "-p" / "s1.jsonl",
        [
            assistant("a", "claude-opus-5-5", NOW - 3 * HOUR, output=1, cwd="/srv/app"),
            assistant("b", "claude-opus-5-5", NOW - HOUR, output=1, cwd="/srv/app/jev-mcp"),
        ],
    )
    report = usage.build_report(Policy.load(), 24, now=NOW, root=root, ledger=tmp_path / "l.jsonl")
    assert list(report["by_project"]) == ["/srv/app"]
    assert report["by_project"]["/srv/app"]["requests"] == 2


def with_content(record, text):
    record["message"]["content"] = [{"type": "text", "text": text}]
    return record


def test_output_reconciled_with_cost_state(tmp_path):
    root = tmp_path / "projects"
    proj = root / "-p"
    write_jsonl(
        proj / "s1.jsonl",
        [
            with_content(assistant("m1", "claude-opus-5-5", NOW - HOUR, output=3, cwd="/srv/app"), "x" * 100),
            {
                "type": "cost-state",
                "sessionId": "s1",
                "startTime": (NOW - 2 * HOUR) * 1000,
                "modelUsage": {"claude-opus-5-5": {"outputTokens": 4000}},
            },
        ],
    )
    sub = proj / "s1" / "subagents"
    worker = with_content(assistant("w1", "claude-opus-5-5", NOW - HOUR, output=2), "y" * 300)
    write_jsonl(sub / "agent-a.jsonl", [worker])
    (sub / "agent-a.meta.json").write_text(json.dumps({"agentType": "implement-medium"}))
    report = usage.build_report(Policy.load(), 24, now=NOW, root=root, ledger=tmp_path / "l.jsonl")
    assert report["totals"]["output_tokens"] == 4000
    assert report["totals"]["output_basis"] == {"reconciled": 2}
    assert report["by_agent"]["implement-medium"]["output_tokens"] == 3000  # 300 of 400 content chars
    assert report["by_agent"][usage.MAIN]["output_tokens"] == 1000


def test_output_estimated_when_snapshot_is_stale_or_missing(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(
        root / "-p" / "s1.jsonl",
        [
            {
                "type": "cost-state",
                "sessionId": "s1",
                "startTime": (NOW - 2 * HOUR) * 1000,
                "modelUsage": {"claude-opus-5-5": {"outputTokens": 999999}},
            },
            # Activity after the snapshot: it no longer covers the session, so it must not be used.
            with_content(assistant("m1", "claude-opus-5-5", NOW - HOUR, output=3, cwd="/srv/app"), "x" * 250),
            with_content(assistant("m2", "claude-opus-5-5", NOW - HOUR, output=500, cwd="/srv/app"), "x" * 25),
        ],
    )
    report = usage.build_report(Policy.load(), 24, now=NOW, root=root, ledger=tmp_path / "l.jsonl")
    assert report["totals"]["output_tokens"] == 100 + 500  # 250 chars / 2.5; recorded 500 beats estimate 10
    assert report["totals"]["output_basis"] == {"estimated": 1, "recorded": 1}
    assert "Output tokens:" in usage.render(report)
