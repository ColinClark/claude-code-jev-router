"""Routing policy (lanes, ladder, limits) and the deterministic hard gates."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .schemas import Evidence

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "policy" / "policy.json"
CLASS_ORDER = ["SMALL", "MEDIUM", "HIGH", "ESCALATE"]


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    version: str
    lanes: dict[str, dict]
    ladder: list[str]
    classes: dict[str, dict]
    security_min_class: str
    confidence_threshold: float
    max_failed_cycles_per_lane: int
    max_cycles_per_unit: int
    jev: dict = field(default_factory=dict)
    retention_hours: float = 24.0
    pricing: dict[str, dict] = field(default_factory=dict)
    first_attempt_max_lane: str | None = None

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Policy:
        path = Path(path or os.environ.get("ROUTER_POLICY") or DEFAULT_POLICY_PATH)
        raw = json.loads(path.read_text())
        limits = raw["limits"]
        policy = cls(
            version=raw["policy_version"],
            lanes=raw["lanes"],
            ladder=raw["ladder"],
            classes=raw["classes"],
            security_min_class=raw.get("security_sensitive_min_class", "HIGH"),
            confidence_threshold=float(limits["confidence_threshold"]),
            max_failed_cycles_per_lane=int(limits["max_failed_cycles_per_lane"]),
            max_cycles_per_unit=int(limits["max_cycles_per_unit"]),
            jev=raw.get("jev", {}),
            retention_hours=float(raw.get("retention_hours", 24)),
            pricing={k: v for k, v in raw.get("pricing", {}).items() if not k.startswith("_")},
            first_attempt_max_lane=raw.get("first_attempt_max_lane"),
        )
        for lane in policy.ladder:
            if lane not in policy.lanes:
                raise PolicyError(f"ladder lane {lane} is not defined")
        if policy.first_attempt_max_lane and policy.first_attempt_max_lane not in policy.ladder:
            raise PolicyError(f"first_attempt_max_lane {policy.first_attempt_max_lane} is not a ladder lane")
        for name, spec in policy.classes.items():
            if spec["lane"] not in policy.ladder:
                raise PolicyError(f"class {name} maps to non-ladder lane {spec['lane']}")
        return policy

    def route(self, lane: str) -> dict:
        spec = self.lanes[lane]
        return {"lane": lane, "model": spec["model"], "effort": spec["effort"], "agent": spec["agent"]}

    def check_ladder_lanes(self, lanes: list[str]) -> list[str]:
        """Validate that every lane is a deployed implementation lane; return them in ladder order."""
        unknown = [lane for lane in lanes if lane not in self.ladder]
        if unknown:
            raise PolicyError(f"not implementation lanes under policy {self.version}: {unknown}")
        return [lane for lane in self.ladder if lane in lanes]

    def next_up(self, lane: str, available: list[str]) -> str | None:
        idx = self.ladder.index(lane)
        return next((lane_ for lane_ in self.ladder[idx + 1 :] if lane_ in available), None)

    def next_down(self, lane: str, available: list[str]) -> str | None:
        idx = self.ladder.index(lane)
        return next((lane_ for lane_ in reversed(self.ladder[:idx]) if lane_ in available), None)

    def lane_for_class(self, cls: str, available: list[str]) -> str:
        """Class's lane if available, else the nearest available lane above it, else the highest below."""
        target = self.classes[cls]["lane"]
        if target in available:
            return target
        return self.next_up(target, available) or self.next_down(target, available)


def raise_class(cls: str) -> str:
    """One class stronger, capped at ESCALATE."""
    return CLASS_ORDER[min(CLASS_ORDER.index(cls) + 1, len(CLASS_ORDER) - 1)]


def floor_class(cls: str, floor: str) -> str:
    """The stronger of cls and floor."""
    return CLASS_ORDER[max(CLASS_ORDER.index(cls), CLASS_ORDER.index(floor))]


@dataclass(frozen=True)
class Gate:
    passed: bool
    needs_verify: bool
    reasons: list[str]


def hard_gates(evidence: Evidence) -> Gate:
    """Deterministic completion gates. Jev can never override a failure reported here."""
    failed: list[str] = []
    unverified: list[str] = []
    for check in evidence.checks:
        if check.status == "FAIL":
            failed.append(f"check {check.name} FAIL (exit {check.exit_code})")
        elif check.status in ("NOT_RUN", "ERROR"):
            unverified.append(f"check {check.name} {check.status}")
    if not any(c.status == "PASS" for c in evidence.checks):
        unverified.append("no passing check in evidence")
    for crit in evidence.criteria:
        if crit.status == "UNSATISFIED":
            failed.append(f"criterion {crit.id} UNSATISFIED")
        elif crit.status == "UNKNOWN":
            unverified.append(f"criterion {crit.id} UNKNOWN")
    if not evidence.criteria:
        unverified.append("no acceptance criteria in evidence")
    if not evidence.scope_ok:
        failed.append("diff is outside the allowed scope")
    if evidence.known_failures:
        failed.append(f"{len(evidence.known_failures)} known failure(s)")
    return Gate(
        passed=not failed and not unverified, needs_verify=bool(unverified) and not failed, reasons=failed + unverified
    )
