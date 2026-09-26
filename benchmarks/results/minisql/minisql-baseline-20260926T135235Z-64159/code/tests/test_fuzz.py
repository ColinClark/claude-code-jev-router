"""Randomized differential testing against sqlite3."""

import random
import sqlite3

import pytest

from minisql import Database, SQLError

from .conftest import typed

COLUMNS = {
    "a": [("x", "INTEGER"), ("y", "REAL"), ("s", "TEXT"), ("k", "INTEGER")],
    "b": [("x", "INTEGER"), ("z", "TEXT"), ("w", "REAL")],
}


def random_value(rng, typ):
    if rng.random() < 0.15:
        return "NULL"
    if typ == "INTEGER":
        return str(rng.choice([0, 1, 2, 3, -1, -7, 10, 42, rng.randint(-100, 100)]))
    if typ == "REAL":
        return rng.choice(["0.0", "1.5", "-2.25", "3.0", "0.1", "100.0", "-0.5", "2.5"])
    word = rng.choice(["abc", "ABC", "Abc", "b", "", "a%c", "x_y", "10", "2", "hello", "1.5"])
    return "'" + word + "'"


def random_expr(rng, cols, depth=0, allow_agg=False, agg_cols=None):
    """Random expression; leaves use `cols`, aggregate arguments use `agg_cols`."""
    r = rng.random()
    if depth >= 3 or r < 0.3:
        if cols and rng.random() < 0.65:
            return rng.choice(cols)
        return rng.choice(["0", "1", "2", "-3", "2.5", "0.5", "'abc'", "'10'", "NULL", "'a%'"])
    sub = lambda: random_expr(rng, cols, depth + 1, allow_agg, agg_cols)  # noqa: E731
    choice = rng.randrange(14 if allow_agg else 13)
    if choice == 0:
        return f"({sub()} {rng.choice(['+', '-', '*', '/', '%'])} {sub()})"
    if choice == 1:
        return f"({sub()} {rng.choice(['=', '!=', '<', '<=', '>', '>=', '<>', '=='])} {sub()})"
    if choice == 2:
        return f"({sub()} {rng.choice(['AND', 'OR'])} {sub()})"
    if choice == 3:
        return f"(NOT {sub()})"
    if choice == 4:
        return f"({sub()} IS {rng.choice(['', 'NOT '])}NULL)"
    if choice == 5:
        items = ", ".join(sub() for _ in range(rng.randint(1, 3)))
        return f"({sub()} {rng.choice(['', 'NOT '])}IN ({items}))"
    if choice == 6:
        return f"({sub()} {rng.choice(['', 'NOT '])}BETWEEN {sub()} AND {sub()})"
    if choice == 7:
        pat = rng.choice(["'a%'", "'%b%'", "'_bc'", "'ABC'", "'%'", "'1%'", sub()])
        return f"({sub()} {rng.choice(['', 'NOT '])}LIKE {pat})"
    if choice == 8:
        return f"(-{sub()})"
    if choice == 9:
        return f"({sub()} || {sub()})"
    if choice == 10:
        return f"(CASE WHEN {sub()} THEN {sub()} ELSE {sub()} END)"
    if choice == 11:
        return f"({sub()} IS {rng.choice(['', 'NOT '])}{sub()})"
    if choice == 12:
        return f"coalesce({sub()}, {sub()})"
    func = rng.choice(["count", "sum", "avg", "min", "max", "count"])
    arg = random_expr(rng, agg_cols or cols, depth + 1, False)
    distinct = "DISTINCT " if rng.random() < 0.2 else ""
    if func == "count" and rng.random() < 0.3:
        return "count(*)"
    return f"{func}({distinct}{arg})"


def untyped(row):
    return tuple(v for _, v in row)


def aliased(items):
    return [f"{item} AS c{i}" for i, item in enumerate(items, 1)]


class Fuzzer:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.db = Database()
        self.lite = sqlite3.connect(":memory:")
        for name, cols in COLUMNS.items():
            ddl = f"CREATE TABLE {name} ({', '.join(f'{c} {t}' for c, t in cols)})"
            self.both(ddl)
            n = self.rng.randint(0, 12)
            for _ in range(n):
                vals = ", ".join(random_value(self.rng, t) for _, t in cols)
                self.both(f"INSERT INTO {name} VALUES ({vals})")

    def both(self, sql):
        self.lite.execute(sql)
        self.db.execute(sql)

    def compare(self, sql, ordered):
        try:
            expected = typed(self.lite.execute(sql).fetchall())
        except sqlite3.Error:
            with pytest.raises(SQLError):
                self.db.execute(sql)
            return
        actual = typed(self.db.execute(sql))
        if ordered:
            # Rows tied on 0 vs 0.0 may come out in either order (SQLite's join order),
            # so check the order on plain values and the typed values as a multiset.
            assert [untyped(r) for r in actual] == [untyped(r) for r in expected], sql
        if "DISTINCT" in sql:
            # DISTINCT keeps an arbitrary one of equal rows such as (0,) and (0.0,).
            actual = [untyped(r) for r in actual]
            expected = [untyped(r) for r in expected]
        assert sorted(actual, key=repr) == sorted(expected, key=repr), sql

    def query(self):
        rng = self.rng
        join = rng.random() < 0.4
        if join and rng.random() < 0.3:
            cols = (
                [f"a.{c}" for c, _ in COLUMNS["a"]]
                + [f"b.{c}" for c, _ in COLUMNS["b"]]
                + [f"b2.{c}" for c, _ in COLUMNS["b"]]
            )
            k1, k2 = rng.choice(["JOIN", "LEFT JOIN"]), rng.choice(["JOIN", "LEFT JOIN"])
            on2 = rng.choice(["b2.x = a.k", "b2.z = b.z", random_expr(rng, cols, 2)])
            source = f"a {k1} b ON a.x = b.x {k2} b AS b2 ON {on2}"
        elif join:
            cols = [f"a.{c}" for c, _ in COLUMNS["a"]] + [f"b.{c}" for c, _ in COLUMNS["b"]]
            kind = rng.choice(["JOIN", "LEFT JOIN"])
            on = rng.choice(["a.x = b.x", "a.k = b.x", random_expr(rng, cols, 1)])
            source = f"a {kind} b ON {on}"
        else:
            cols = [c for c, _ in COLUMNS["a"]]
            source = "a"
        where = f" WHERE {random_expr(rng, cols)}" if rng.random() < 0.6 else ""
        mode = rng.random()
        if mode < 0.3:
            # grouped query
            keys = rng.sample(cols, rng.randint(1, 2))
            items = keys + [random_expr(rng, keys, 1, True, cols) for _ in range(2)]
            items.append(rng.choice(["count(*)", f"sum({keys[0]})", f"max({keys[0]})"]))
            having = ""
            if rng.random() < 0.4:
                having = f" HAVING {random_expr(rng, keys, 1, True, cols)}"
            sql = f"SELECT {', '.join(aliased(items))} FROM {source}{where} "
            sql += f"GROUP BY {', '.join(keys)}"
            sql += having
        elif mode < 0.45:
            aggs = [
                rng.choice(["count(*)", "sum", "avg", "min", "max", "count", "total"])
                for _ in range(3)
            ]
            items = [a if a == "count(*)" else f"{a}({random_expr(rng, cols, 2)})" for a in aggs]
            sql = f"SELECT {', '.join(aliased(items))} FROM {source}{where}"
        else:
            items = [random_expr(rng, cols) for _ in range(rng.randint(1, 3))]
            distinct = "DISTINCT " if rng.random() < 0.2 else ""
            sql = f"SELECT {distinct}{', '.join(aliased(items))} FROM {source}{where}"
        ordered = False
        if rng.random() < 0.5:
            n = len(items)
            terms = [f"{i} {rng.choice(['ASC', 'DESC'])}" for i in range(1, n + 1)]
            rng.shuffle(terms)
            if rng.random() < 0.5 and "DISTINCT " not in sql[:16]:
                # Lead with an arbitrary expression (maybe via an alias); positions break ties.
                if mode < 0.45:
                    lead = random_expr(rng, keys if mode < 0.3 else [], 1, True, cols)
                else:
                    lead = random_expr(rng, cols, 1)
                # SQLite folds e.g. "x AND 0" into the literal 0 (a position), so wrap it.
                lead = f"coalesce({lead}, NULL)"
                if rng.random() < 0.3:
                    lead = f"c{rng.randint(1, n)}"
                terms.insert(0, f"{lead} {rng.choice(['ASC', 'DESC'])}")
            sql += " ORDER BY " + ", ".join(terms)
            ordered = True
            if rng.random() < 0.3:
                sql += f" LIMIT {rng.randint(0, 5)} OFFSET {rng.randint(0, 3)}"
        return sql, ordered

    def mutate(self):
        rng = self.rng
        cols = [c for c, _ in COLUMNS["a"]]
        if rng.random() < 0.5:
            col, typ = rng.choice(COLUMNS["a"])
            value = random_expr(rng, cols, 2) if rng.random() < 0.5 else random_value(rng, typ)
            self.compare_dml(f"UPDATE a SET {col} = {value} WHERE {random_expr(rng, cols)}")
        else:
            self.compare_dml(f"DELETE FROM a WHERE {random_expr(rng, cols)}")

    def compare_dml(self, sql):
        try:
            self.lite.execute(sql)
        except sqlite3.Error:
            with pytest.raises(SQLError):
                self.db.execute(sql)
            return
        self.db.execute(sql)
        self.compare("SELECT * FROM a", ordered=False)


@pytest.mark.parametrize("seed", range(60))
def test_random_queries(seed):
    fuzzer = Fuzzer(seed)
    for step in range(60):
        sql, ordered = fuzzer.query()
        fuzzer.compare(sql, ordered)
        if step % 20 == 19:
            fuzzer.mutate()
