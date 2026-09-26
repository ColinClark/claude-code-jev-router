"""The implementation must not use re (or any other regex library)."""

import ast
from pathlib import Path

import miniregex

FORBIDDEN = {"re", "regex", "sre_compile", "sre_parse", "_sre", "fnmatch"}


def test_no_regex_imports():
    src = Path(miniregex.__file__).parent
    files = list(src.glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert not FORBIDDEN.intersection(names), f"{path.name} imports {names}"
