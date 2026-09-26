"""The miniregex package must not use the re module (or other regex libraries)."""

from __future__ import annotations

import ast
from pathlib import Path

import miniregex

FORBIDDEN = {"re", "regex", "sre_compile", "sre_parse", "sre_constants", "_sre"}


def _package_files() -> list[Path]:
    root = Path(miniregex.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert files
    return files


def test_no_regex_imports() -> None:
    for path in _package_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
            ):
                names = [getattr(a, "value", "") for a in node.args[:1]]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                assert top not in FORBIDDEN, f"{path.name} imports {name}"
                assert not name.startswith("re."), f"{path.name} imports {name}"
