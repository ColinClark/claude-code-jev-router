"""router-report: summarize Claude Code model usage and router decisions over a recent window.

  router-report                       last 24 hours, text tables
  router-report --hours 6             a different window
  router-report --project statista    only projects whose path contains this text
  router-report --format markdown     markdown tables (used by the /router-report skill)
  router-report --format json         machine-readable

Usage comes from Claude Code's own session transcripts (~/.claude/projects), so no extra
usage log is kept: each API request is counted once (deduplicated by requestId). Router
decisions come from the decision ledger, which is pruned to the policy's retention window
every time this report runs. Costs are API-equivalent estimates from policy.json pricing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import retention
from .policy import Policy

MAIN = "main session"
DATE_SUFFIX = re.compile(r"-\d{8}$")
PRICING_NOTE = "API-equivalent estimate from policy.json pricing; not your actual bill on a subscription plan."


@dataclass
class Call:
    model: str
    effort: str | None
    ts: float
    project: str
    session: str
    agent: str
    agent_file: str
    input: int = 0
    output: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0

    def merge(self, other: Call) -> None:
        # A request is written once per content block with growing counts; keep the final (max) values.
        for name in ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read"):
            setattr(self, name, max(getattr(self, name), getattr(other, name)))


@dataclass
class Bucket:
    requests: int = 0
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    cost: float = 0.0
    unpriced: int = 0
    efforts: Counter = field(default_factory=Counter)
    models: Counter = field(default_factory=Counter)
    runs: set = field(default_factory=set)

    def add(self, call: Call, cost: float | None) -> None:
        self.requests += 1
        self.input += call.input
        self.output += call.output
        self.cache_write += call.cache_write_5m + call.cache_write_1h
        self.cache_read += call.cache_read
        if cost is None:
            self.unpriced += 1
        else:
            self.cost += cost
        self.efforts[call.effort or "default"] += 1
        self.models[call.model] += 1
        self.runs.add(call.agent_file)

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "runs": len(self.runs),
            "input_tokens": self.input,
            "output_tokens": self.output,
            "cache_write_tokens": self.cache_write,
            "cache_read_tokens": self.cache_read,
            "est_cost_usd": round(self.cost, 4),
            "unpriced_requests": self.unpriced,
            "models": dict(self.models.most_common()),
            "efforts": dict(self.efforts.most_common()),
        }


# ---- transcript scanning -----------------------------------------------------


def projects_dir() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return base / "projects"


def _agent_type(path: Path) -> str:
    meta = path.with_name(path.stem + ".meta.json")
    try:
        return json.loads(meta.read_text()).get("agentType") or "subagent"
    except (OSError, ValueError):
        return "subagent"


def _parse_ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def transcript_files(root: Path, since: float) -> list[tuple[Path, str]]:
    """Main-session and subagent transcripts modified inside the window (older files cannot hold newer calls)."""
    files = [(p, MAIN) for p in root.glob("*/*.jsonl")]
    files += [(p, _agent_type(p)) for p in root.glob("*/*/subagents/*.jsonl")]
    out = []
    for path, agent in files:
        try:
            if path.stat().st_mtime >= since:
                out.append((path, agent))
        except OSError:
            continue
    return out


def read_calls(path: Path, agent: str, since: float, until: float) -> dict[str, Call]:
    calls: dict[str, Call] = {}
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return calls
    with fh:
        for line in fh:
            if '"assistant"' not in line or '"usage"' not in line:
                continue  # cheap pre-filter before parsing
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            model, usage = msg.get("model"), msg.get("usage")
            if not model or model.startswith("<") or not isinstance(usage, dict):
                continue
            ts = _parse_ts(rec.get("timestamp"))
            if ts is None or not since <= ts <= until:
                continue
            breakdown = usage.get("cache_creation") or {}
            w5 = breakdown.get("ephemeral_5m_input_tokens")
            w1h = breakdown.get("ephemeral_1h_input_tokens") or 0
            if w5 is None:  # no breakdown: treat all cache writes as 5-minute writes
                w5 = (usage.get("cache_creation_input_tokens") or 0) - w1h
            call = Call(
                model=model,
                effort=rec.get("effort"),
                ts=ts,
                project=rec.get("cwd") or path.parent.name,
                session=rec.get("sessionId") or path.stem,
                agent=agent,
                agent_file=str(path),
                input=usage.get("input_tokens") or 0,
                output=usage.get("output_tokens") or 0,
                cache_write_5m=max(w5, 0),
                cache_write_1h=w1h,
                cache_read=usage.get("cache_read_input_tokens") or 0,
            )
            key = rec.get("requestId") or msg.get("id") or rec.get("uuid") or f"{path}:{len(calls)}"
            if key in calls:
                calls[key].merge(call)
            else:
                calls[key] = call
    return calls


# ---- pricing -----------------------------------------------------------------


def price_for(model: str, pricing: dict[str, dict]) -> dict | None:
    return pricing.get(model) or pricing.get(DATE_SUFFIX.sub("", model))


def cost_of(call: Call, pricing: dict[str, dict]) -> float | None:
    p = price_for(call.model, pricing)
    if p is None:
        return None
    return (
        call.input * p["input"]
        + call.output * p["output"]
        + call.cache_write_5m * p.get("cache_write_5m", p["input"] * 1.25)
        + call.cache_write_1h * p.get("cache_write_1h", p["input"] * 2)
        + call.cache_read * p.get("cache_read", p["input"] * 0.1)
    ) / 1_000_000


# ---- report ------------------------------------------------------------------


WORKTREE = re.compile(r"/\.claude/worktrees/[^/]+(/.*)?$")


def project_name(cwd: str) -> str:
    """Fold Claude Code worktrees into their repository and shorten the home directory."""
    path = WORKTREE.sub("", cwd)
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + "/") else path


def _same_model(a: str, b: str) -> bool:
    return DATE_SUFFIX.sub("", a) == DATE_SUFFIX.sub("", b)


def build_report(
    policy: Policy,
    hours: float,
    project: str | None = None,
    now: float | None = None,
    root: Path | None = None,
    ledger: Path | None = None,
    top: int = 10,
) -> dict:
    until = now if now is not None else time.time()
    since = until - hours * 3600
    root = root or projects_dir()

    calls: dict[str, Call] = {}
    for path, agent in transcript_files(root, since):
        for key, call in read_calls(path, agent, since, until).items():
            if key in calls:
                calls[key].merge(call)
            else:
                calls[key] = call

    # Attribute every call to the project its session started in (cwd drifts as Claude cds around).
    first: dict[str, Call] = {}
    for call in calls.values():
        seen = first.get(call.session)
        if seen is None or (call.agent == MAIN, -call.ts) > (seen.agent == MAIN, -seen.ts):
            first[call.session] = call
    for call in calls.values():
        call.project = project_name(first[call.session].project)
    if project:
        calls = {k: c for k, c in calls.items() if project.lower() in c.project.lower()}

    agent_to_lane = {spec["agent"]: lane for lane, spec in policy.lanes.items()}
    totals, by_model = Bucket(), defaultdict(Bucket)
    by_agent, by_project = defaultdict(Bucket), defaultdict(Bucket)
    for call in calls.values():
        cost = cost_of(call, policy.pricing)
        for bucket in (totals, by_model[call.model], by_agent[call.agent], by_project[call.project]):
            bucket.add(call, cost)

    agents = {}
    mismatches = []
    for agent, bucket in sorted(by_agent.items(), key=lambda kv: -kv[1].cost):
        lane = agent_to_lane.get(agent)
        entry = {"lane": lane or ("—" if agent == MAIN else "not a router lane"), **bucket.as_dict()}
        if lane:
            expected = policy.lanes[lane]["model"]
            wrong = {m: n for m, n in bucket.models.items() if not _same_model(m, expected)}
            if wrong:
                entry["expected_model"] = expected
                mismatches.append({"agent": agent, "lane": lane, "expected_model": expected, "observed": wrong})
        agents[agent] = entry

    routed = sum(b.cost for a, b in by_agent.items() if a in agent_to_lane)
    projects = sorted(by_project.items(), key=lambda kv: -kv[1].cost)[:top]
    return {
        "window": {
            "hours": hours,
            "since": datetime.fromtimestamp(since, UTC).isoformat(timespec="seconds"),
            "until": datetime.fromtimestamp(until, UTC).isoformat(timespec="seconds"),
            "project_filter": project,
        },
        "totals": totals.as_dict() | {"sessions": len({c.session for c in calls.values()})},
        "routed_share_of_cost": round(routed / totals.cost, 4) if totals.cost else None,
        "by_model": {m: b.as_dict() for m, b in sorted(by_model.items(), key=lambda kv: -kv[1].cost)},
        "by_agent": agents,
        "by_project": {p: b.as_dict() for p, b in projects},
        "lane_model_mismatches": mismatches,
        "router_decisions": decision_summary(ledger or retention.ledger_path(), since, until, policy),
        "pricing_note": PRICING_NOTE,
    }


def decision_summary(ledger: Path, since: float, until: float, policy: Policy) -> dict:
    retention.prune_jsonl(ledger, retention.cutoff_for(policy.retention_hours, until))
    entries = []
    try:
        for line in ledger.read_text().splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if since <= float(entry.get("ts", 0)) <= until:
                entries.append(entry)
    except FileNotFoundError:
        pass
    confidences = [e["confidence"] for e in entries if e.get("decided_by") == "jev" and e.get("confidence") is not None]
    lanes = Counter((e.get("route") or {}).get("lane") for e in entries if e.get("tool") == "classify_task")
    return {
        "decisions": len(entries),
        "tasks": len({e.get("task_id") for e in entries}),
        "by_tool": dict(Counter(e.get("tool") or "unknown" for e in entries).most_common()),
        "actions": dict(Counter(e["action"] for e in entries if e.get("action")).most_common()),
        "classes": dict(Counter(e["class"] for e in entries if e.get("class")).most_common()),
        "initial_lanes": {k: v for k, v in lanes.most_common() if k},
        "decided_by": dict(Counter(e.get("decided_by") for e in entries).most_common()),
        "avg_jev_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "retention_hours": policy.retention_hours,
    }


# ---- rendering -----------------------------------------------------------------


def _n(value: int) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if value >= size:
            return f"{value / size:.1f}{unit}"
    return str(value)


def _usd(bucket: dict) -> str:
    text = f"${bucket['est_cost_usd']:,.2f}"
    return text + ("*" if bucket["unpriced_requests"] else "")


def _table(headers: list[str], rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
        out += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(out)
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows]
    return "\n".join(out)


def render(report: dict, markdown: bool = False) -> str:
    w, t = report["window"], report["totals"]
    h, sub = ("## ", "### ") if markdown else ("", "")
    scope = f" · project filter: {w['project_filter']}" if w["project_filter"] else ""
    parts = [
        f"{h}Model usage — last {w['hours']:g}h ({w['since']} → {w['until']}){scope}",
        f"{t['requests']} API requests across {t['sessions']} sessions · "
        f"input {_n(t['input_tokens'])} · output {_n(t['output_tokens'])} · "
        f"cache write {_n(t['cache_write_tokens'])} · cache read {_n(t['cache_read_tokens'])} · "
        f"est. cost {_usd(t)}",
    ]
    if report["routed_share_of_cost"] is not None:
        parts.append(f"Router lanes account for {report['routed_share_of_cost']:.0%} of estimated cost.")

    stats = ["requests", "input (incl. cache)", "output", "effort", "est. cost"]

    def row(name: str, b: dict) -> list[str]:
        effort = ", ".join(f"{k}:{v}" for k, v in b["efforts"].items())
        tokens_in = b["input_tokens"] + b["cache_read_tokens"] + b["cache_write_tokens"]
        return [name, str(b["requests"]), _n(tokens_in), _n(b["output_tokens"]), effort, _usd(b)]

    def section(title: str, headers: list[str], rows: list[list[str]]) -> list[str]:
        return ["", f"{sub}{title}", _table(headers, rows, markdown)]

    parts += section("By model", ["model", *stats], [row(m, b) for m, b in report["by_model"].items()])
    parts += section(
        "By lane / agent", ["lane", "agent", *stats], [[b["lane"], *row(a, b)] for a, b in report["by_agent"].items()]
    )
    parts += section("Top projects", ["project", *stats], [row(p, b) for p, b in report["by_project"].items()])

    if report["lane_model_mismatches"]:
        parts += ["", f"{sub}Lane/model mismatches"]
        for m in report["lane_model_mismatches"]:
            observed = ", ".join(f"{k} ({v} requests)" for k, v in m["observed"].items())
            parts.append(f"- {m['agent']} ({m['lane']}) expected {m['expected_model']}, ran on {observed}")

    d = report["router_decisions"]
    parts += ["", f"{sub}Router decisions"]
    if d["decisions"]:
        fmt = lambda c: ", ".join(f"{k} {v}" for k, v in c.items()) or "none"  # noqa: E731
        parts += [
            f"- {d['decisions']} decisions for {d['tasks']} tasks · decided by: {fmt(d['decided_by'])}"
            + (f" · avg Jev confidence {d['avg_jev_confidence']}" if d["avg_jev_confidence"] is not None else ""),
            f"- initial lanes: {fmt(d['initial_lanes'])}",
            f"- actions: {fmt(d['actions'])}",
        ]
    else:
        parts.append("- no router decisions in this window")
    parts.append(f"- decision log keeps {d['retention_hours']:g}h (policy.json `retention_hours`)")
    if t["unpriced_requests"]:
        parts.append("\n* includes requests on models with no price in policy.json; their cost is not counted.")
    parts.append(("\n_" if markdown else "\n") + report["pricing_note"] + ("_" if markdown else ""))
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router-report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--hours", type=float, default=24, help="window size in hours (default 24)")
    parser.add_argument("--project", help="only include projects whose path contains this text")
    parser.add_argument("--top", type=int, default=10, help="number of projects to list (default 10)")
    parser.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    args = parser.parse_args(argv)
    if args.hours <= 0:
        parser.error("--hours must be positive")

    report = build_report(Policy.load(), args.hours, project=args.project, top=args.top)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render(report, markdown=args.format == "markdown"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
