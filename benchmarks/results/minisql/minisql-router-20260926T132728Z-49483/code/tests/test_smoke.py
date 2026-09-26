"""Smoke tests for unit 1: lexer/parser, expression semantics, and DML."""

import sqlite3

import pytest

from minisql import Database, SQLError
from minisql.expressions import eval_expr
from minisql.nodes import (
    BinaryOp,
    ColumnRef,
    ExprItem,
    FunctionCall,
    Join,
    OrderItem,
    Select,
    StarItem,
    TableRef,
)
from minisql.parser import parse, parse_expression

EXPRESSIONS = [
    "1 + 2", "7 / 2", "-7 / 2", "7 / 0", "7 % 0", "7.0 / 2", "7 / 2.0", "-7 % 3", "7 % -3",
    "5.5 % 2", "5 % 2.5", "7.0 / 0", "9223372036854775807 + 1", "-9223372036854775808",
    "'3' + 4", "'abc' + 1", "' 12abc' + 1", "'1e3' + 0", "-'3x'", "+'abc'",
    "1 || 2", "1.0 || 'x'", "0.1 || ''", "1e20 || ''", "NULL || 'a'", "'a' || 'b'",
    "1 = 1", "1 == 1.0", "1 != 2", "1 <> 1", "1 < 2", "2 <= 1", "'a' > 'B'", "2 < 'a'",
    "1 = NULL", "NULL = NULL", "1 = 1 < 2",
    "NULL AND 0", "NULL AND 1", "NULL OR 1", "NULL OR 0", "NOT NULL", "NOT 0", "NOT 'abc'",
    "'1x' AND 1", "'x' OR 0",
    "NULL IS NULL", "1 IS NULL", "1 IS NOT NULL", "NULL IS NOT NULL", "1 IS 1.0", "NULL IS 1",
    "1 IN (1, 2)", "3 IN (1, 2)", "3 NOT IN (1, 2)", "1 IN (2, NULL)", "1 IN (1, NULL)",
    "NULL IN (1)", "NULL NOT IN (1)", "3 NOT IN (1, NULL)",
    "2 BETWEEN 1 AND 3", "5 BETWEEN 1 AND 3", "5 NOT BETWEEN 1 AND 3", "3 BETWEEN 1 AND NULL",
    "5 BETWEEN 1 AND NULL", "NULL BETWEEN 1 AND 2",
    "'abc' LIKE 'a%'", "'ABC' LIKE 'a_c'", "'abc' NOT LIKE 'b%'", "NULL LIKE 'a'",
    "'a%b' LIKE 'a\\%b' ESCAPE '\\'", "'axb' LIKE 'a\\%b' ESCAPE '\\'", "'hello' GLOB 'h*o'",
    "-(1 + 2) * 3", "(1 + 2) * 3", "2 + 3 * 4", "- - 3", "1.5 * 2", "3 - 5.0",
    "CASE WHEN 1 THEN 'y' ELSE 'n' END", "CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' END",
    "CAST('12abc' AS INTEGER)", "CAST(3.9 AS INTEGER)", "CAST(5 AS TEXT)", "CAST('3.0' AS NUMERIC)",
    "coalesce(NULL, 2)", "abs(-3)", "length('abc')", "upper('abc')", "max(1, 3, 2)",
    "round(2.5)", "round(3.14159, 2)", "typeof(1.0)", "substr('hello', 2, 3)", "TRUE", "~5",
]


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_expression_matches_sqlite(expr):
    conn = sqlite3.connect(":memory:")
    expected = conn.execute(f"SELECT {expr}").fetchone()[0]
    got = eval_expr(parse_expression(expr))
    assert got == expected and type(got) is type(expected), (expr, got, expected)


DML_SCRIPT = [
    "CREATE TABLE t (id INTEGER, name TEXT, score REAL)",
    "INSERT INTO t VALUES (1, 'alice', 90), (2, 'bob', 85.5), (3, 'carol', NULL)",
    "INSERT INTO t (name, id) VALUES ('dave', 4)",
    "INSERT INTO t VALUES ('5', 6, '7.5')",
    "UPDATE t SET score = score + 1 WHERE score IS NOT NULL",
    "UPDATE t SET name = upper(name), id = id * 10 WHERE name LIKE 'B%' OR id > 3",
    "DELETE FROM t WHERE score < 88",
    "INSERT INTO t (id) VALUES (7)",
    "DELETE FROM t WHERE id = 7",
]


def test_dml_matches_sqlite():
    db = Database()
    conn = sqlite3.connect(":memory:")
    for sql in DML_SCRIPT:
        assert db.execute(sql) == []
        conn.execute(sql)
    expected = conn.execute("SELECT * FROM t").fetchall()
    got = db.tables["t"].rows
    assert got == expected
    assert [tuple(type(v) for v in r) for r in got] == [
        tuple(type(v) for v in r) for r in expected
    ]


def test_delete_all_and_case_insensitive():
    db = Database()
    db.execute("create table Foo (A integer)")
    db.execute("INSERT INTO foo (a) values (1), (2)")
    db.execute("delete FROM FOO")
    assert db.tables["foo"].rows == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC 1",
        "CREATE TABLE",
        "INSERT INTO t VALUES (1",
        "INSERT INTO nope VALUES (1)",
        "INSERT INTO t (zzz) VALUES (1)",
        "INSERT INTO t VALUES (1, 2, 3)",
        "UPDATE t SET zzz = 1",
        "UPDATE t SET a = zzz",
        "DELETE FROM t WHERE zzz = 1",
        "DELETE FROM nope",
        "CREATE TABLE t (a INTEGER)",
        "DELETE FROM t WHERE count(*) > 1",
        "UPDATE t SET a = nosuchfn(1)",
        "SELECT 1; SELECT 2",
        "'unterminated",
    ],
)
def test_errors(sql):
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


def test_parse_full_select():
    stmt = parse(
        "SELECT DISTINCT e.name AS n, d.*, COUNT(*), count(DISTINCT e.dept) c, SUM(e.salary) "
        "FROM emp AS e JOIN dept d ON e.dept_id = d.id "
        "LEFT OUTER JOIN loc l ON l.id = d.loc "
        "WHERE e.salary > 10 GROUP BY e.dept HAVING COUNT(*) > 1 "
        "ORDER BY n DESC, 2 LIMIT 5 OFFSET 2;"
    )
    assert isinstance(stmt, Select)
    assert stmt.distinct
    assert stmt.columns[0] == ExprItem(ColumnRef("name", "e"), "n")
    assert stmt.columns[1] == StarItem("d")
    assert stmt.columns[2] == ExprItem(FunctionCall("COUNT", (), False, True))
    assert stmt.columns[3] == ExprItem(FunctionCall("COUNT", (ColumnRef("dept", "e"),), True), "c")
    assert stmt.from_table == TableRef("emp", "e")
    assert stmt.joins[0] == Join(
        "INNER", TableRef("dept", "d"), BinaryOp("=", ColumnRef("dept_id", "e"), ColumnRef("id", "d"))
    )
    assert stmt.joins[1].kind == "LEFT"
    assert stmt.group_by == (ColumnRef("dept", "e"),)
    assert stmt.having is not None
    assert stmt.order_by[0] == OrderItem(ColumnRef("n"), True)
    assert stmt.limit is not None and stmt.offset is not None


def test_parse_select_star_simple():
    stmt = parse("select * from t")
    assert isinstance(stmt, Select)
    assert stmt.columns == (StarItem(None),)
    assert stmt.from_table == TableRef("t")


AFFINITY_WHERES = [
    "a = 10", "a = '10'", "b = '10'", "b = 10", "a < 5", "b < '5'", "c = 1", "c = '1'",
    "a IN (10, 9)", "b IN ('10', 'x')", "a BETWEEN 1 AND 99", "d = 2", "d = '2'", "a > b",
    "c = 1.0", "e = 1", "e = '1'", "a LIKE '1%'", "b + 0 = 10", "NOT a", "a || b = '1010'",
]


@pytest.mark.parametrize("where", AFFINITY_WHERES)
def test_where_affinity_matches_sqlite(where):
    setup = [
        "CREATE TABLE t (a TEXT, b INTEGER, c REAL, d NUMERIC, e)",
        (
            "INSERT INTO t VALUES ('10', 10, 1, '2', '1'), ('9', '9', '1.0', 2.0, 1),"
            " ('abc', 'xyz', 'q', 'x', NULL), (NULL, NULL, NULL, NULL, 1.5), (5, 5.0, 5, 5.5, 'a')"
        ),
    ]
    db = Database()
    conn = sqlite3.connect(":memory:")
    for sql in setup:
        db.execute(sql)
        conn.execute(sql)
    stmt = f"DELETE FROM t WHERE {where}"
    db.execute(stmt)
    conn.execute(stmt)
    expected = conn.execute("SELECT * FROM t").fetchall()
    got = db.tables["t"].rows
    assert got == expected
    assert [tuple(type(v) for v in r) for r in got] == [
        tuple(type(v) for v in r) for r in expected
    ]
