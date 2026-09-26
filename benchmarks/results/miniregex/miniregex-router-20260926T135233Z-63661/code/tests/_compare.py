"""Helpers comparing miniregex against Python's re module."""

import re

import miniregex


def match_info(m, ngroups):
    if m is None:
        return None
    return (
        m.span(),
        m.group(),
        m.groups(),
        tuple(m.span(i) for i in range(ngroups + 1)),
        tuple(m.group(i) for i in range(ngroups + 1)),
    )


def assert_same(pattern, text, methods=("search", "match", "fullmatch", "findall")):
    ref = re.compile(pattern)
    mine = miniregex.compile(pattern)
    for meth in methods:
        if meth == "findall":
            got, exp = mine.findall(text), ref.findall(text)
        else:
            got = match_info(getattr(mine, meth)(text), ref.groups)
            exp = match_info(getattr(ref, meth)(text), ref.groups)
        assert got == exp, f"{meth} {pattern!r} on {text!r}: got {got!r}, expected {exp!r}"
