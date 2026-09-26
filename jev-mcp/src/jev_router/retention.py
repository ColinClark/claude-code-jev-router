"""Retention for the router's own logs, so they stay bounded to a recent window.

Claude Code's transcripts are not touched here; Claude Code prunes those itself
(`cleanupPeriodDays`, 30 days by default).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

DEFAULT_LEDGER = Path("~/.local/state/claude-router/decisions.jsonl").expanduser()


def ledger_path() -> Path:
    return Path(os.environ.get("ROUTER_LEDGER") or DEFAULT_LEDGER)


def append_entry(path: Path, entry: dict) -> float:
    """Append one timestamped JSON line to a log. Failures are swallowed: logging must never break routing."""
    now = time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({**entry, "ts": now}) + "\n")
    except OSError:
        pass
    return now


def read_entries(path: Path, since: float = 0.0) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
            if float(entry.get("ts", 0)) >= since:
                out.append(entry)
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def prune_jsonl(path: Path, cutoff: float) -> int:
    """Rewrite a JSONL log keeping only entries with `ts` >= cutoff. Returns the number of entries dropped."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return 0
    kept = []
    for line in lines:
        try:
            if float(json.loads(line).get("ts", 0)) >= cutoff:
                kept.append(line)
        except (ValueError, TypeError, AttributeError):
            continue  # malformed lines are dropped
    dropped = len(lines) - len(kept)
    if dropped:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(line + "\n" for line in kept))
        os.replace(tmp, path)
    return dropped


def prune_dirs(parent: Path, cutoff: float, keep: Path | None = None) -> int:
    """Delete subdirectories of parent last modified before cutoff. Returns the number removed."""
    removed = 0
    try:
        children = list(parent.iterdir())
    except FileNotFoundError:
        return 0
    for child in children:
        if child.is_dir() and child != keep and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def prune_files(parent: Path, pattern: str, cutoff: float) -> int:
    """Delete files matching pattern in parent last modified before cutoff."""
    removed = 0
    for path in parent.glob(pattern):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def cutoff_for(hours: float, now: float | None = None) -> float:
    return (now if now is not None else time.time()) - hours * 3600
