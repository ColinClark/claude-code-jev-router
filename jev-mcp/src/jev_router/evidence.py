"""router-evidence: trusted, deterministic evidence collector.

  router-evidence fingerprint                   print the current workspace fingerprint
  router-evidence verify FP                     exit 0 iff the workspace still matches FP
  router-evidence collect --check NAME=CMD ...  run checks, emit an evidence JSON packet
        [--allow GLOB ...] [--na NAME ...] [--timeout SECONDS]

The fingerprint covers HEAD, staged and unstaged diffs and the contents of
untracked (non-ignored) files, so any edit after the checks invalidates it.
Full check logs are kept under <git-common-dir>/router-evidence/; the packet
carries only bounded summaries.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import retention
from .policy import Policy


def _retention_hours() -> float:
    try:
        return Policy.load().retention_hours
    except (OSError, ValueError, KeyError):
        return 24.0


MAX_DIFF_SUMMARY = 2000
LOG_TAIL_BYTES = 4000


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _untracked(repo: Path) -> list[str]:
    out = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(p for p in out.decode().split("\0") if p)


def fingerprint(repo: Path) -> str:
    h = hashlib.sha256()
    try:
        head = _git(repo, "rev-parse", "HEAD").strip()
    except subprocess.CalledProcessError:
        head = b"no-head"
    h.update(b"head\0" + head)
    h.update(b"\0staged\0" + _git(repo, "diff", "--cached", "--binary", "--no-ext-diff"))
    h.update(b"\0unstaged\0" + _git(repo, "diff", "--binary", "--no-ext-diff"))
    for rel in _untracked(repo):
        path = repo / rel
        h.update(b"\0untracked\0" + rel.encode())
        try:
            h.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"non-file")
        except OSError:
            h.update(b"unreadable")
    return "wsfp-" + h.hexdigest()[:24]


def changed_files(repo: Path) -> list[str]:
    try:
        tracked = _git(repo, "diff", "HEAD", "--name-only", "-z").decode().split("\0")
    except subprocess.CalledProcessError:  # no commits yet
        tracked = _git(repo, "diff", "--cached", "--name-only", "-z").decode().split("\0")
    return sorted({p for p in tracked if p} | set(_untracked(repo)))


def diff_summary(repo: Path, files: list[str]) -> str:
    try:
        stat = _git(repo, "diff", "HEAD", "--shortstat").decode().strip()
    except subprocess.CalledProcessError:
        stat = ""
    untracked = _untracked(repo)
    text = (
        f"{len(files)} file(s) changed; {stat or 'no tracked diff'}; {len(untracked)} untracked. Files: "
        + ", ".join(files)
    )
    return text if len(text) <= MAX_DIFF_SUMMARY else text[: MAX_DIFF_SUMMARY - 20] + " ...[more files]"


def run_check(repo: Path, name: str, cmd: str, timeout: float, log_dir: Path) -> dict:
    log_path = log_dir / f"{name}.log"
    try:
        proc = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, timeout=timeout)
        output = proc.stdout + proc.stderr
        status, code = ("PASS" if proc.returncode == 0 else "FAIL"), proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"") + (exc.stderr or b"") + f"\n[timed out after {timeout}s]".encode()
        status, code = "ERROR", None
    except OSError as exc:
        output, status, code = str(exc).encode(), "ERROR", None
    log_path.write_bytes(output)
    tail = output[-LOG_TAIL_BYTES:].decode(errors="replace")
    return {"name": name, "status": status, "exit_code": code, "command": cmd, "log": str(log_path), "tail": tail}


def collect(repo: Path, checks: list[tuple[str, str]], allow: list[str], na: list[str], timeout: float) -> dict:
    before = fingerprint(repo)
    log_dir = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
        / "router-evidence"
        / before
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir.touch()  # refresh mtime so a re-collect on the same fingerprint counts as recent
    retention.prune_dirs(log_dir.parent, retention.cutoff_for(_retention_hours()), keep=log_dir)

    results = [run_check(repo, name, cmd, timeout, log_dir) for name, cmd in checks]
    results += [{"name": name, "status": "NOT_APPLICABLE", "exit_code": None} for name in na]
    after = fingerprint(repo)

    files = changed_files(repo)
    out_of_scope = [f for f in files if allow and not any(fnmatch.fnmatch(f, g) for g in allow)]
    packet = {
        # Pass `evidence` (plus your criteria) to the jev tools; the rest is for the orchestrator.
        "evidence": {
            "fingerprint": after,
            "checks": [{k: r[k] for k in ("name", "status", "exit_code")} for r in results],
            "criteria": [],
            "scope_ok": (not out_of_scope) if allow else None,
            "known_failures": [
                f"{r['name']} failed (exit {r['exit_code']})" for r in results if r["status"] in ("FAIL", "ERROR")
            ],
            "diff_summary": diff_summary(repo, files),
        },
        "stale": before != after,
        "changed_files": files,
        "out_of_scope": out_of_scope,
        "log_dir": str(log_dir),
        "check_details": [{k: r.get(k) for k in ("name", "command", "log", "tail")} for r in results if "command" in r],
    }
    if packet["stale"]:
        packet["warning"] = (
            "Checks modified the workspace (e.g. a formatter); re-run collect before relying on this evidence."
        )
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router-evidence", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fingerprint")
    ver = sub.add_parser("verify")
    ver.add_argument("fingerprint")
    col = sub.add_parser("collect")
    col.add_argument("--check", action="append", default=[], metavar="NAME=CMD")
    col.add_argument(
        "--allow", action="append", default=[], metavar="GLOB", help="allowed paths; omit to leave scope_ok null"
    )
    col.add_argument(
        "--na", action="append", default=[], metavar="NAME", help="check accepted as NOT_APPLICABLE by the contract"
    )
    col.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args(argv)

    repo = Path(_git(Path(args.repo), "rev-parse", "--show-toplevel").decode().strip())
    if args.cmd == "fingerprint":
        print(fingerprint(repo))
        return 0
    if args.cmd == "verify":
        current = fingerprint(repo)
        ok = current == args.fingerprint
        print(json.dumps({"match": ok, "expected": args.fingerprint, "current": current}))
        return 0 if ok else 1
    checks = []
    for spec in args.check:
        name, sep, cmd = spec.partition("=")
        if not sep or not name or not cmd:
            parser.error(f"--check must be NAME=CMD, got {spec!r}")
        checks.append((name, cmd))
    print(json.dumps(collect(repo, checks, args.allow, args.na, args.timeout), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
