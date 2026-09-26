"""Strict request contracts for the four decision tools.

Unknown fields are rejected, sizes are bounded, and oversized input is refused
rather than truncated so that evidence is never silently lost.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0"
MAX_TEXT = 2000
MAX_CRITERIA = 20
MAX_CHECKS = 40
MAX_REQUEST_BYTES = 16 * 1024

Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(max_length=300)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]

CheckStatus = Literal["PASS", "FAIL", "NOT_RUN", "ERROR", "NOT_APPLICABLE"]
CriterionStatus = Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(Strict):
    schema_version: Literal["1.0"]
    request_id: Id
    task_id: Id
    policy_version: Id

    @model_validator(mode="after")
    def _bounded(self):
        if len(json.dumps(self.model_dump(mode="json"))) > MAX_REQUEST_BYTES:
            raise ValueError(f"serialized request exceeds {MAX_REQUEST_BYTES} bytes")
        return self


class Check(Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    status: CheckStatus
    exit_code: int | None

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "PASS" and self.exit_code != 0:
            raise ValueError(f"check {self.name!r}: PASS requires exit_code 0")
        if self.status in ("NOT_RUN", "NOT_APPLICABLE") and self.exit_code is not None:
            raise ValueError(f"check {self.name!r}: {self.status} requires exit_code null")
        if self.status == "FAIL" and self.exit_code == 0:
            raise ValueError(f"check {self.name!r}: FAIL cannot have exit_code 0")
        return self


class Criterion(Strict):
    id: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    status: CriterionStatus
    evidence_ref: Short


class Evidence(Strict):
    fingerprint: Id
    checks: list[Check] = Field(max_length=MAX_CHECKS)
    criteria: list[Criterion] = Field(max_length=MAX_CRITERIA)
    scope_ok: bool
    known_failures: list[Short] = Field(default_factory=list, max_length=20)
    diff_summary: Annotated[str, StringConstraints(max_length=MAX_TEXT)] = ""


Lane = Annotated[str, StringConstraints(min_length=1, max_length=40)]
Signal = Annotated[str, StringConstraints(max_length=200)] | bool | int | float


class ClassifyRequest(Identity):
    task: Text
    acceptance_criteria: list[Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=list, max_length=MAX_CRITERIA
    )
    signals: dict[Annotated[str, StringConstraints(max_length=50)], Signal] = Field(default_factory=dict, max_length=20)
    available_lanes: list[Lane] = Field(min_length=1, max_length=10)


class ProgressRequest(Identity):
    current_lane: Lane
    attempt: int = Field(ge=1, le=100)
    evidence: Evidence


class EscalationRequest(Identity):
    current_lane: Lane
    direction: Literal["up", "down", "reassess"]
    attempt: int = Field(ge=1, le=100)
    evidence: Evidence
    available_lanes: list[Lane] = Field(min_length=1, max_length=10)


class CompletionRequest(Identity):
    residual_question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    evidence: Evidence
