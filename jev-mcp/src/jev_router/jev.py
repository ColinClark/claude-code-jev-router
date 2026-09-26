"""Minimal Jev (TypeSafe System One) client.

The API key is read only inside this process, from TYPESAFE_API_KEY or the
policy's env file. It is never included in return values, errors or logs.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

RETRYABLE_STATUS = {429, 529, 500, 502, 503, 504}


class JevError(Exception):
    """code is JEV_UNAVAILABLE (transport/auth/quota) or INVALID_DECISION (malformed reply)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict[str, float]


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


class JevClient:
    def __init__(
        self,
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        model: str = "jev-latest",
        timeout_seconds: float = 10.0,
        env_file: str = "~/.config/jev/.env",
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout_seconds
        self.env_file = Path(env_file).expanduser()
        self._transport = transport
        self._sleep = sleep

    def _api_key(self) -> str:
        key = os.environ.get("TYPESAFE_API_KEY") or _read_env_file(self.env_file).get("TYPESAFE_API_KEY")
        if not key:
            raise JevError("JEV_UNAVAILABLE", "Jev credentials are not configured")
        return key

    def choice(self, state, instructions: str, options: dict[str, str]) -> ChoiceAnswer:
        body = {
            "model": self.model,
            "state": state,
            "questions": {"decision": {"type": "choice", "instructions": instructions, "criteria": options}},
        }
        data = self._post(body)
        try:
            answer = data["answers"]["decision"]
            choice = answer["choice"]
            confidence = float(answer["confidence"])
            probabilities = {str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()}
        except (KeyError, TypeError, ValueError):
            raise JevError("INVALID_DECISION", "Jev reply did not match the choice answer schema") from None
        if answer.get("type") != "choice" or choice not in options or not 0.0 <= confidence <= 1.0:
            raise JevError("INVALID_DECISION", "Jev reply contained a disallowed choice or confidence")
        return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities)

    def _post(self, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        attempts = 2  # one bounded transport retry with jitter
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                    resp = client.post(self.endpoint, json=body, headers=headers)
            except httpx.HTTPError as exc:
                if last:
                    raise JevError("JEV_UNAVAILABLE", f"Jev transport error: {type(exc).__name__}") from None
                self._sleep(0.5 + random.random())
                continue
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    raise JevError("INVALID_DECISION", "Jev reply was not JSON") from None
            if resp.status_code in (401, 403):
                raise JevError("JEV_UNAVAILABLE", f"Jev authentication failed (HTTP {resp.status_code})")
            if resp.status_code in RETRYABLE_STATUS and not last:
                self._sleep(0.5 + random.random())
                continue
            raise JevError("JEV_UNAVAILABLE", f"Jev request failed (HTTP {resp.status_code})")
        raise JevError("JEV_UNAVAILABLE", "Jev request failed")
