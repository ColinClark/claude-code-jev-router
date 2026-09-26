"""Print "tests failures errors skipped" from a pytest JUnit XML report (zeros if missing or unreadable)."""

import sys
import xml.etree.ElementTree as ET


def counts(path: str) -> tuple[int, int, int, int]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return 0, 0, 0, 0
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = [0, 0, 0, 0]
    for suite in suites:
        for i, key in enumerate(("tests", "failures", "errors", "skipped")):
            total[i] += int(suite.get(key, 0))
    return tuple(total)


if __name__ == "__main__":
    print(*counts(sys.argv[1] if len(sys.argv) > 1 else ""))
