"""Random SQL generator used for differential testing against sqlite3."""

from __future__ import annotations

import random
import sqlite3

from minisql import Database, SQLError
from minisql.values import sort_key

SCHEMA = {
    "t1": [("a", "INTEGER"), ("b", "INTEGER"), ("c", "TEXT"), ("d", "REAL")],
    "t2": [("a", "INTEGER"), ("e", "TEXT"), ("f", "REAL")],
    "t3": [("g", "INTEGER"), ("h", "TEXT")],
}

TEXTS = ["abc", "ABC", "Abd", "x", "", "10", "2", "a%b", "a_c", "hello world", "é", "-3", "1.5"]


def random_value(rng: random.Random, col_type: str):
    if rng.random() < 0.2:
        return None
    if col_type == "INTEGER":
        return rng.choice([0, 1, 2, 3, -1, -7, 10, 42, 100, rng.randint(-50, 50)])
    if col_type == "REAL":
        return rng.choice([0.0, 0.5, 1.5, -2.25, 3.0, 10.0, 1e10, rng.randint(-100, 100) / 8])
    return rng.choice(TEXTS)


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


def setup_statements(rng: random.Random, rows: int = 12) -> list[str]:
    stmts = []
    for name, cols in SCHEMA.items():
        stmts.append(f"CREATE TABLE {name} ({', '.join(f'{c} {t}' for c, t in cols)})")
        values = []
        for _ in range(rng.randint(0, rows)):
            values.append("(" + ", ".join(sql_literal(random_value(rng, t)) for _, t in cols) + ")")
        if values:
            stmts.append(f"INSERT INTO {name} VALUES {', '.join(values)}")
    return stmts


class ExprGen:
    def __init__(self, rng: random.Random, columns: list[str], aggregates: bool = False):
        self.rng = rng
        self.columns = columns
        self.aggregates = aggregates

    def literal(self) -> str:
        r = self.rng.random()
        if r < 0.1:
            return "NULL"
        if r < 0.5:
            return str(self.rng.choice([0, 1, 2, 3, -1, 5, 10, 100]))
        if r < 0.7:
            return self.rng.choice(["0.5", "1.5", "2.0", "-0.25", "3e2", "0.0"])
        return sql_literal(self.rng.choice(TEXTS + ["%", "a%", "%c", "_b%", "A__"]))

    def leaf(self) -> str:
        if self.columns and self.rng.random() < 0.65:
            return self.rng.choice(self.columns)
        return self.literal()

    def expr(self, depth: int = 0) -> str:
        rng = self.rng
        if depth > 2 or rng.random() < 0.3:
            return self.leaf()
        kind = rng.randrange(14)
        e = lambda: self.expr(depth + 1)  # noqa: E731
        if kind == 0:
            return f"({e()} {rng.choice(['+', '-', '*', '/', '%'])} {e()})"
        if kind == 1:
            return f"({e()} {rng.choice(['=', '==', '!=', '<>', '<', '<=', '>', '>='])} {e()})"
        if kind == 2:
            return f"({e()} {rng.choice(['AND', 'OR'])} {e()})"
        if kind == 3:
            return f"(NOT {e()})"
        if kind == 4:
            return f"({e()} IS {rng.choice(['', 'NOT '])}NULL)"
        if kind == 5:
            items = ", ".join(e() for _ in range(rng.randint(1, 3)))
            return f"({e()} {rng.choice(['', 'NOT '])}IN ({items}))"
        if kind == 6:
            return f"({e()} {rng.choice(['', 'NOT '])}BETWEEN {e()} AND {e()})"
        if kind == 7:
            return f"({e()} {rng.choice(['', 'NOT '])}LIKE {e()})"
        if kind == 8:
            return f"(-{e()})"
        if kind == 9:
            return f"({e()} || {e()})"
        if kind == 10:
            return f"(CASE WHEN {e()} THEN {e()} ELSE {e()} END)"
        if kind == 11:
            if rng.random() < 0.4:
                return f"{rng.choice(['coalesce', 'ifnull'])}({e()}, {e()})"
            return f"{rng.choice(['abs', 'length', 'upper', 'lower'])}({e()})"
        if kind == 12:
            return f"({e()} IS {rng.choice(['', 'NOT '])}{e()})"
        return f"CAST({e()} AS {rng.choice(['INTEGER', 'REAL', 'TEXT'])})"

    def aggregate(self) -> str:
        rng = self.rng
        func = rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL"])
        if func == "COUNT" and rng.random() < 0.3:
            return "COUNT(*)"
        distinct = "DISTINCT " if rng.random() < 0.2 else ""
        return f"{func}({distinct}{self.expr(1)})"


def random_select(rng: random.Random) -> str:
    tables = list(SCHEMA)
    first = rng.choice(tables)
    from_sql = f"{first} AS x"
    columns = [f"x.{c}" for c, _ in SCHEMA[first]]
    if rng.random() < 0.5:
        second = rng.choice(tables)
        join = rng.choice(["JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "INNER JOIN"])
        ycols = [f"y.{c}" for c, _ in SCHEMA[second]]
        on = f"{rng.choice(columns)} {rng.choice(['=', '<', '>=', '!='])} {rng.choice(ycols)}"
        from_sql += f" {join} {second} y ON {on}"
        columns += ycols
    gen = ExprGen(rng, columns)
    where = f" WHERE {gen.expr()}" if rng.random() < 0.6 else ""
    if rng.random() < 0.4:
        group_cols = rng.sample(columns, rng.randint(0, 2))
        items = list(group_cols) + [gen.aggregate() for _ in range(rng.randint(1, 3))]
        group = f" GROUP BY {', '.join(group_cols)}" if group_cols else ""
        having = f" HAVING {gen.aggregate()} {rng.choice(['>', '<', '>=', '='])} {gen.literal()}" \
            if group_cols and rng.random() < 0.3 else ""
        order = " ORDER BY " + ", ".join(
            f"{i + 1} {rng.choice(['ASC', 'DESC'])}" for i in range(len(items))
        )
        return f"SELECT {', '.join(items)} FROM {from_sql}{where}{group}{having}{order}"
    items = [gen.expr() for _ in range(rng.randint(1, 4))]
    distinct = "DISTINCT " if rng.random() < 0.2 else ""
    order = ""
    ordered = rng.random() < 0.7
    if ordered:
        order = " ORDER BY " + ", ".join(
            f"{i + 1} {rng.choice(['ASC', 'DESC', ''])}" for i in range(len(items))
        )
    limit = ""
    if ordered and rng.random() < 0.3:
        limit = f" LIMIT {rng.randint(0, 5)}" + (
            f" OFFSET {rng.randint(0, 3)}" if rng.random() < 0.5 else ""
        )
    return f"SELECT {distinct}{', '.join(items)} FROM {from_sql}{where}{order}{limit}"


def run_both(stmts: list[str], query: str):
    """Returns (sqlite_result, minisql_result); results are rows or ("error", message)."""
    conn = sqlite3.connect(":memory:")
    db = Database()
    for stmt in stmts:
        try:
            conn.execute(stmt)
            ok = True
        except sqlite3.Error:
            ok = False
        try:
            db.execute(stmt)
            if not ok:
                return ("error", stmt), ("no error", stmt)
        except SQLError:
            if ok:
                return ("no error", stmt), ("error", stmt)
    try:
        expected = conn.execute(query).fetchall()
    except (sqlite3.Error, OverflowError) as exc:
        expected = ("error", str(exc))
    try:
        actual = db.execute(query)
    except SQLError as exc:
        actual = ("error", str(exc))
    return expected, actual


def normalize(result, ordered: bool):
    if isinstance(result, tuple):
        return result[0] if result[0] != "error" else "error"
    rows = [tuple((type(v).__name__, v) for v in row) for row in result]
    if not ordered:
        rows.sort(key=lambda row: [sort_key(v) for _, v in row])
    return rows


def random_mixed_value(rng: random.Random):
    """Any-typed value, to exercise column affinity on insert."""
    return rng.choice(
        [None, 0, 1, -5, 7, 2.0, 2.5, -0.5, 1e20, "12", " 7 ", "3.0", "1e2", "abc", "", "-4", "x1"]
    )


def random_dml(rng: random.Random) -> list[str]:
    """Mixed-type inserts plus random UPDATE/DELETE statements on t1."""
    stmts = []
    for _ in range(rng.randint(0, 3)):
        vals = ", ".join(sql_literal(random_mixed_value(rng)) for _ in range(4))
        stmts.append(f"INSERT INTO t1 VALUES ({vals})")
    if rng.random() < 0.5:
        stmts.append(f"INSERT INTO t1 (c, a) VALUES ({sql_literal(rng.choice(TEXTS))}, 9)")
    gen = ExprGen(rng, ["a", "b", "c", "d"])
    for _ in range(rng.randint(0, 3)):
        if rng.random() < 0.6:
            col = rng.choice(["a", "b", "c", "d"])
            sets = f"{col} = {gen.expr(1)}"
            if rng.random() < 0.4:
                sets += f", {rng.choice(['a', 'b', 'c', 'd'])} = {gen.expr(1)}"
            where = f" WHERE {gen.expr()}" if rng.random() < 0.7 else ""
            stmts.append(f"UPDATE t1 SET {sets}{where}")
        else:
            stmts.append(f"DELETE FROM t1 WHERE {gen.expr()}")
    return stmts


def random_ordered_select(rng: random.Random) -> tuple[str, int]:
    """SELECT whose first k output columns are exactly the ORDER BY keys.

    Returns (sql, k). Ties in those keys may legitimately come back in any order.
    """
    columns = [f"x.{c}" for c, _ in SCHEMA["t1"]]
    from_sql = "t1 x"
    if rng.random() < 0.6:
        from_sql += " LEFT JOIN t2 y ON x.a = y.a"
        columns += [f"y.{c}" for c, _ in SCHEMA["t2"]]
        if rng.random() < 0.5:
            join = rng.choice(["JOIN", "LEFT JOIN"])
            from_sql += f" {join} t3 z ON z.g {rng.choice(['=', '<'])} x.b"
            columns += [f"z.{c}" for c, _ in SCHEMA["t3"]]
    gen = ExprGen(rng, columns)
    where = f" WHERE {gen.expr()}" if rng.random() < 0.4 else ""
    if rng.random() < 0.5:
        # Aggregate query grouped by expressions, ordered by aggregates and keys.
        keys = [gen.expr(1) for _ in range(rng.randint(1, 2))]
        aggs = [gen.aggregate() for _ in range(rng.randint(1, 2))]
        items = [f"{k} AS k{i}" for i, k in enumerate(keys)] + aggs
        group = " GROUP BY " + ", ".join(rng.choice([k, f"k{i}"])
                                          for i, k in enumerate(keys))
        having = f" HAVING {gen.aggregate()} IS NOT NULL" if rng.random() < 0.3 else ""
        order_terms = [f"k{i}" for i in range(len(keys))] + [str(len(keys) + 1)]
        rng.shuffle(order_terms)
        order = ", ".join(f"{t} {rng.choice(['ASC', 'DESC', ''])}" for t in order_terms)
        # Reorder output so that ORDER BY keys come first, in ORDER BY order.
        index = {f"k{i}": i for i in range(len(keys))}
        index[str(len(keys) + 1)] = len(keys)
        first = [items[index[t]] for t in order_terms]
        rest = [it for i, it in enumerate(items) if i not in {index[t] for t in order_terms}]
        order_sql = ", ".join(
            f"{i + 1} {o.split(' ', 1)[1] if ' ' in o else ''}"
            for i, o in enumerate(order.split(", "))
        )
        sql = (f"SELECT {', '.join(first + rest)} FROM {from_sql}{where}{group}{having}"
               f" ORDER BY {order_sql}")
        return sql, len(order_terms)
    keys = [gen.expr(1) for _ in range(rng.randint(1, 2))]
    others = [gen.expr() for _ in range(rng.randint(0, 2))]
    items = [f"{k} AS o{i}" for i, k in enumerate(keys)] + others
    order = ", ".join(
        f"{rng.choice([f'o{i}', k, str(i + 1)])} {rng.choice(['ASC', 'DESC', ''])}"
        for i, k in enumerate(keys)
    )
    limit = f" LIMIT {rng.randint(1, 6)}" if rng.random() < 0.2 else ""
    return f"SELECT {', '.join(items)} FROM {from_sql}{where} ORDER BY {order}{limit}", len(keys)
