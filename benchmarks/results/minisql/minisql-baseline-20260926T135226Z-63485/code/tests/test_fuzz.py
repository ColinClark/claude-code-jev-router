"""Differential tests: random schemas, data and queries compared against sqlite3."""

import random

import pytest
from sqlgen import (
    normalize,
    random_dml,
    random_ordered_select,
    random_select,
    run_both,
    setup_statements,
)

from minisql.values import sort_key


def keys(rows, k):
    return [[sort_key(v) for v in row[:k]] for row in rows]


@pytest.mark.parametrize("chunk", range(10))
def test_random_selects(chunk):
    for seed in range(chunk * 100, chunk * 100 + 100):
        rng = random.Random(seed)
        stmts = setup_statements(rng)
        sql = random_select(rng)
        expected, actual = run_both(stmts, sql)
        context = f"seed={seed}\n{sql}\nsqlite={expected}\nminisql={actual}"
        assert normalize(actual, False) == normalize(expected, False), context
        if " ORDER BY " in sql and isinstance(expected, list):
            assert keys(actual, 99) == keys(expected, 99), context


@pytest.mark.parametrize("chunk", range(10))
def test_random_dml_and_ordered_selects(chunk):
    for seed in range(chunk * 100, chunk * 100 + 100):
        rng = random.Random(seed)
        stmts = setup_statements(rng) + random_dml(rng)
        sql, k = random_ordered_select(rng)
        expected, actual = run_both(stmts, sql)
        context = f"seed={seed}\n{stmts}\n{sql}\nsqlite={expected}\nminisql={actual}"
        if isinstance(expected, list) and isinstance(actual, list):
            assert keys(actual, k) == keys(expected, k), context
            if " LIMIT " not in sql:
                assert normalize(actual, False) == normalize(expected, False), context
        else:
            assert normalize(actual, False) == normalize(expected, False), context
        full_expected, full_actual = run_both(stmts, "SELECT * FROM t1")
        assert normalize(full_actual, False) == normalize(full_expected, False), context
