"""Differential tests for expression semantics (SELECT without FROM)."""

from __future__ import annotations

import pytest

from tests.conftest import Diff

ARITHMETIC = [
    "1 + 2", "7 - 10", "3 * 4", "7 / 2", "-7 / 2", "7 / -2", "-7 / -2", "7 % 2", "-7 % 2",
    "7 % -2", "-7 % -2", "1 % -1", "5 % -3", "-5 % 3", "5.5 % 2", "-5.5 % 2", "5 % 2.5",
    "5.0 % -3", "1 / 0", "1.0 / 0", "1 / 0.0", "1 % 0", "1.5 % 0", "6 / 4.0", "6.0 / 4",
    "3 * 1.0", "1 + 1.0", "2.0 - 1", "2 * 3.0", "0.1 + 0.2", "1 / 3.0", "2 / 3",
    "9223372036854775807 + 1", "9223372036854775807 * 2", "-9223372036854775808 - 1",
    "9223372036854775807 % 2", "-9223372036854775808 % -1", "-9223372036854775808 / -1",
    "9223372036854775807 / -1", "-(-9223372036854775808)", "-(9223372036854775807)",
    "-1", "+1", "-1.5", "+1.5", "- -1", "1 - -1", "1 - - - 1", "-2 * 3", "-2 * -3", "-(2 + 3)",
    "NULL + 1", "1 + NULL", "NULL * NULL", "NULL / 0", "-NULL", "+NULL", "NULL % 2",
    "1e3", "1E-2", "12.5e1", "0.0", "00012", "1.e1", ".5", "5.", "1.5e300 * 1e10",
]

TEXT_ARITH = [
    "'3abc' + 1", "'abc' + 1", "'3.5x' + 1", "' 3' + 1", "'3.' + 1", "'1e2x' + 1", "'' + 1",
    "'3.0' + 1", "'-3' + 1", "'+3' + 1", "'0x10' + 1", "'.5' + 1", "'3 ' + 1", "'1e' + 1",
    "'1e+' + 1", "'-' + 1", "'- 3' + 1", "'1_000' + 1", "'1.5.5' + 1", "'inf' + 1", "'1e2' + 1",
    "'00012' + 1", "'9223372036854775808' + 1", "'9223372036854775807' + 1",
    "'-9223372036854775808' + 0", "-'3abc'", "+'3abc'", "-'abc'", "-'2.5'", "'5' * '2'",
    "'5' / '2'", "'5.0' / '2'", "'7' % '2'", "'a' - 'b'", "'12' || 3", "'abc' + 'def'",
]

CONCAT = [
    "'ab' || 'cd'", "'ab' || 'cd' || 'ef'", "1 || 2", "1.5 || ''", "1 || ''", "-2.0 || 'x'",
    "0.000001 || ''", "1e100 || ''", "1e20 || ''", "0.1 + 0.2 || ''", "1.0 / 3 || ''",
    "100.0 || ''", "1e15 || ''", "1e-5 || ''", "123456789012345678.0 || ''", "2.5e-10 || ''",
    "-0.0 || ''", "1e16 || ''", "NULL || 'a'", "'a' || NULL", "NULL || NULL", "'x' || 1 || 'y'",
    "'it''s' || ' ok'", "'' || ''", "2 - 1 || 3", "1 || 2 + 3", "1 || 2 * 3", "-1 || 2",
]

COMPARISON = [
    "1 = 1", "1 = 2", "1 == 1", "1 != 2", "1 <> 1", "1 < 2", "2 < 1", "1 <= 1", "1 >= 2",
    "1 > 0", "1 = 1.0", "1.5 > 1", "2 > 1.5", "1 < 1.5", "'1' = 1", "1 < 'a'", "'a' < 1",
    "'a' < 'b'", "'a' = 'A'", "'a' < 'B'", "'B' < 'a'", "'é' > 'z'", "'abc' < 'abd'",
    "'' < 'a'", "'a' < 'ab'", "'abc' = 'abc'", "NULL = NULL", "NULL = 1", "1 = NULL",
    "NULL < 1", "NULL <> NULL", "'a' = NULL", "9007199254740993 = 9007199254740992.0",
    "9007199254740993 > 9007199254740992.0", "0 = -0.0", "-0.0 < 0", "-0.0 = 0.0", "1 = 1 = 1",
    "1 < 2 = 1", "1 = 2 = 0", "1 + 1 = 2", "1 < 2 < 3", "3 > 2 > 1", "'10' < '9'", "10 < 9",
    "1 IS 1.0", "1 IS '1'", "NULL IS NULL", "NULL IS 1", "1 IS NULL", "1 IS NOT NULL",
    "NULL IS NOT NULL", "1 IS NOT 1", "1 IS NOT 2", "'a' IS 'a'", "NULL IS NOT 1",
    "1 = 1 IS 1", "1 = 2 IS NULL", "(1 = NULL) IS NULL", "2 IS 1 + 1",
]

LOGIC = [
    "NULL AND 0", "NULL AND 1", "0 AND NULL", "1 AND NULL", "NULL OR 1", "NULL OR 0",
    "1 OR NULL", "0 OR NULL", "NULL AND NULL", "NULL OR NULL", "NOT NULL", "NOT 0", "NOT 1",
    "NOT 2", "NOT -1", "NOT 0.0", "NOT 0.5", "NOT 'abc'", "NOT '1'", "NOT ''", "1 AND 1",
    "1 AND 0", "0 OR 0", "0 OR 1", "2 AND 3", "'abc' AND 1", "'1' AND 1", "0.5 AND 1",
    "'a' OR NULL", "'0.0' AND 1", "' 1' AND 1", "'1x' AND 1", "'0x' OR 0", "0.0 OR 0",
    "'' OR 0", "'.1' AND 1", "NOT 1 = 0", "NOT 1 + 1", "NOT 1 AND 0", "NOT 0 OR 0",
    "1 OR 0 AND 0", "(1 OR 0) AND 0", "0 AND 0 OR 1", "0 AND (0 OR 1)", "NOT NOT 1",
    "NOT NOT NULL", "NOT (1 = 1)", "1 = 1 AND 2 = 2", "1 = 1 OR NULL", "NULL AND 1 = 1",
    "NOT NULL = 1", "NOT (NULL = 1)",
]

IN_BETWEEN_LIKE = [
    "1 IN (1, 2)", "3 IN (1, 2)", "1 IN (1, NULL)", "2 IN (1, NULL)", "NULL IN (1, 2)",
    "NULL IN ()", "1 IN ()", "1 NOT IN ()", "2 NOT IN (1, NULL)", "1 NOT IN (1, NULL)",
    "NULL NOT IN (1)", "NULL NOT IN ()", "1 IN (1.0)", "1.0 IN (1)", "'1' IN (1)",
    "1 IN ('1')", "'a' IN ('a', 'b')", "'A' IN ('a')", "1 IN (1 + 0, 2)", "1 NOT IN (2, 3)",
    "5 BETWEEN 1 AND 10", "5 BETWEEN 10 AND 1", "'b' BETWEEN 'a' AND 'c'",
    "5 BETWEEN '1' AND '10'", "1 BETWEEN NULL AND 2", "3 BETWEEN NULL AND 2",
    "NULL BETWEEN 1 AND 2", "1 NOT BETWEEN NULL AND 2", "3 NOT BETWEEN NULL AND 2",
    "1 BETWEEN 1 AND 1", "1 NOT BETWEEN 1 AND 1", "2 BETWEEN 1 AND NULL", "0 BETWEEN 1 AND NULL",
    "1.5 BETWEEN 1 AND 2", "1 BETWEEN 0.5 AND 1.5", "1 BETWEEN 0 AND 2 = 1",
    "1 BETWEEN 1 AND 1 BETWEEN 1 AND 1", "5 BETWEEN 1 AND 3 + 4", "5 BETWEEN 1 + 1 AND 10 - 1",
    "10 LIKE '1%'", "1.5 LIKE '1.5'", "'ABC' LIKE 'abc'", "'abc' LIKE 'ABC'", "'É' LIKE 'é'",
    "'a_c' LIKE 'a\\_c'", "NULL LIKE 'a'", "'a' LIKE NULL", "'abc' LIKE 'A_C'", "'ab' LIKE 'a__'",
    "100 LIKE '1__'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '%b%'",
    "'abc' LIKE '%c'", "'abc' LIKE 'a%'", "'abc' LIKE 'b%'", "'abc' LIKE '_bc'",
    "'abc' LIKE 'abc'", "'abcd' LIKE 'abc'", "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'",
    "'a[b]c' LIKE 'a[b]c'", "'a*c' LIKE 'a*c'", "'abc' NOT LIKE 'a%'", "'abc' NOT LIKE 'x%'",
    "NULL NOT LIKE 'a'", "'a%c' LIKE 'a%c'", "'axc' LIKE 'a%c'", "'a\nb' LIKE 'a_b'",
    "'a\nb' LIKE 'a%b'", "'ÀB' LIKE 'àb'", "'ab' LIKE 'AB'", "'a' LIKE 'A' = 1", "'x' LIKE 'x' + 1",
    "1 IN (1) = 1", "1 = 2 IN (0)", "'abc' LIKE '%' AND 1", "'abc' LIKE 'x' OR 1",
    "1 IN (1) AND 0", "1 BETWEEN 0 AND 2 AND 1", "1 IN (1, 2) IN (1)",
]

PRECEDENCE = [
    "1 + 2 * 3", "(1 + 2) * 3", "6 / 2 * 3", "7 - 2 - 1", "2 * 3 % 4", "8 % 3 * 2",
    "2 - 1 || 3", "1 || 2 + 3", "1 + 2 < 4", "1 < 2 + 3", "1 + 1 = 2", "2 = 1 + 1", "1 < 2 = 1",
    "1 = 1 = 1", "1 = 2 = 0", "NOT 1 = 0", "NOT 1 + 1", "1 OR 0 AND 0", "0 AND 1 OR 1",
    "NOT 0 AND 0", "NOT (0 AND 0)", "- 2 * 3", "-2 + 3", "-(2 + 3)", "-2 - -3", "1 - 2 - 3",
    "2 * 3 / 4", "100 / 10 / 2", "2 || 3 * 4", "1 + 2 || 3", "'a' || 'b' = 'ab'",
    "1 < 2 AND 2 < 3", "1 < 2 OR 1 > 2 AND 0", "5 > 3 = 1 < 2", "3 % 2 = 1 AND 4 % 2 = 0",
    "- 1 < 0", "-1 < 0 = 1", "1 + 2 BETWEEN 2 AND 4", "1 + 2 IN (3)", "2 * 2 LIKE '4'",
]

FUNCTIONS = [
    "typeof(1)", "typeof(1.0)", "typeof('a')", "typeof(NULL)", "typeof(1 = 1)", "typeof(1e0)",
    "typeof(1.)", "typeof(.5)", "typeof(1 + 1.0)", "typeof(7 / 2)", "typeof('3' + 1)",
    "typeof('3.0' + 1)", "typeof(-'x')", "typeof(1 || 2)", "typeof(5.5 % 2)",
    "coalesce(NULL, 1)", "coalesce(NULL, NULL, 'x')", "coalesce(NULL, NULL)", "ifnull(NULL, 'x')",
    "ifnull(1, 'x')", "nullif(1, 1)", "nullif(1, 2)", "nullif(1, 1.0)", "abs(-2)", "abs(-2.5)",
    "abs(NULL)", "abs('x')", "abs('-3')", "length('abc')", "length(123)", "length(1.5)",
    "length(NULL)", "length('')", "length('héllo')", "upper('abcé')", "lower('ABCÉ')",
    "upper(NULL)", "upper(12)", "max(1, 'a')", "min(1, 2.0)", "max(1, NULL)", "min(3, 1, 2)",
    "max(2.0, 2)", "min('b', 'a', 'c')", "TYPEOF(1)", "Coalesce(1, 2)",
]


@pytest.mark.parametrize("expr", ARITHMETIC)
def test_arithmetic(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", TEXT_ARITH)
def test_text_in_arithmetic(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", CONCAT)
def test_concatenation(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", COMPARISON)
def test_comparison(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", LOGIC)
def test_three_valued_logic(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", IN_BETWEEN_LIKE)
def test_in_between_like(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", PRECEDENCE)
def test_precedence(diff: Diff, expr: str) -> None:
    diff.value(expr)


@pytest.mark.parametrize("expr", FUNCTIONS)
def test_scalar_functions(diff: Diff, expr: str) -> None:
    diff.value(expr)


def test_truth_tables_are_exhaustive(diff: Diff) -> None:
    vals = ["NULL", "0", "1"]
    for a in vals:
        for b in vals:
            diff.value(f"{a} AND {b}")
            diff.value(f"{a} OR {b}")
        diff.value(f"NOT {a}")


def test_integer_division_and_modulo_grid(diff: Diff) -> None:
    for a in range(-7, 8):
        for b in range(-3, 4):
            diff.run(f"SELECT {a} / {b}, {a} % {b}, {a}.0 / {b}, {a} % {b}.0, {a}.5 % {b}")


def test_select_without_from_returns_python_types(diff: Diff) -> None:
    row = diff.run("SELECT 1, 1.0, 'a', NULL, 1 = 1, 7 / 2, 7 / 2.0")[0]
    assert [type(v) for v in row] == [int, float, str, type(None), int, int, float]
    assert not any(isinstance(v, bool) for v in row)


def test_select_multiple_columns_and_semicolon(diff: Diff) -> None:
    assert diff.run("SELECT 1 + 1, 'x';") == [(2, "x")]
    assert diff.run("select 1 + 1 AS two, 3 three") == [(2, 3)]


def test_string_literal_escapes(diff: Diff) -> None:
    assert diff.value("'it''s'") == "it's"
    assert diff.value("''''") == "'"
    assert diff.value("''") == ""
    assert diff.value("'a''''b'") == "a''b"


def test_case_insensitive_keywords(diff: Diff) -> None:
    diff.run("sElEcT 1 As x WhErE 1 Is NoT nUlL AnD 2 In (2) oR 0 BeTwEeN 1 AnD 2")
    diff.run("SELECT null, NULL, Null, nulL IS NULL")
