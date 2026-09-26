import pytest

from minisql import Database, SQLError


@pytest.fixture
def people_orders(dual):
    dual.run("CREATE TABLE people (id INTEGER, name TEXT, age INTEGER)")
    dual.run(
        "INSERT INTO people (id, name, age) VALUES "
        "(1, 'Alice', 30), (2, 'Bob', 25), (3, 'Carol', NULL), (4, 'Dave', 25)"
    )
    dual.run("CREATE TABLE orders (id INTEGER, person_id INTEGER, amount REAL)")
    dual.run(
        "INSERT INTO orders (id, person_id, amount) VALUES "
        "(1, 1, 10.5), (2, 1, 5.0), (3, 2, 20.0), (4, 99, 1.0)"
    )
    return dual


def test_select_star(people_orders):
    people_orders.query("SELECT * FROM people")


def test_select_with_where(people_orders):
    people_orders.query("SELECT name FROM people WHERE age >= 30")


def test_select_where_null_comparison_excludes_rows(people_orders):
    people_orders.query("SELECT name FROM people WHERE age > 0")


def test_order_by_asc_nulls_first(people_orders):
    people_orders.query("SELECT name, age FROM people ORDER BY age", ordered=True)


def test_order_by_desc_nulls_last(people_orders):
    people_orders.query("SELECT name, age FROM people ORDER BY age DESC", ordered=True)


def test_order_by_multiple_columns(people_orders):
    people_orders.query(
        "SELECT age, name FROM people ORDER BY age ASC, name DESC", ordered=True
    )


def test_order_by_alias(people_orders):
    people_orders.query(
        "SELECT name AS n, age AS a FROM people ORDER BY a, n", ordered=True
    )


def test_order_by_expression(people_orders):
    people_orders.query("SELECT name, age FROM people ORDER BY age * -1", ordered=True)


def test_limit(people_orders):
    people_orders.query("SELECT name FROM people ORDER BY id LIMIT 2", ordered=True)


def test_limit_offset(people_orders):
    people_orders.query(
        "SELECT name FROM people ORDER BY id LIMIT 2 OFFSET 1", ordered=True
    )


def test_distinct(people_orders):
    people_orders.query("SELECT DISTINCT age FROM people")


def test_distinct_multiple_columns(people_orders):
    people_orders.run("INSERT INTO people (id, name, age) VALUES (5, 'Bob', 25)")
    people_orders.query("SELECT DISTINCT name, age FROM people")


def test_inner_join(people_orders):
    people_orders.query(
        "SELECT people.name, orders.amount FROM people "
        "JOIN orders ON people.id = orders.person_id"
    )


def test_inner_join_with_alias(people_orders):
    people_orders.query(
        "SELECT p.name, o.amount FROM people AS p "
        "JOIN orders AS o ON p.id = o.person_id"
    )


def test_left_join_includes_unmatched_rows_as_null(people_orders):
    people_orders.query(
        "SELECT p.name, o.amount FROM people p "
        "LEFT JOIN orders o ON p.id = o.person_id"
    )


def test_left_outer_join_keyword_variant(people_orders):
    people_orders.query(
        "SELECT p.name, o.amount FROM people p "
        "LEFT OUTER JOIN orders o ON p.id = o.person_id"
    )


def test_multiple_joins(people_orders):
    people_orders.run("CREATE TABLE payments (order_id INTEGER, method TEXT)")
    people_orders.run("INSERT INTO payments VALUES (1, 'card'), (3, 'cash')")
    people_orders.query(
        "SELECT p.name, o.amount, pay.method FROM people p "
        "JOIN orders o ON p.id = o.person_id "
        "LEFT JOIN payments pay ON o.id = pay.order_id"
    )


def test_select_star_with_alias_qualifier(people_orders):
    people_orders.query(
        "SELECT p.* FROM people p JOIN orders o ON p.id = o.person_id"
    )


def test_where_with_join_condition(people_orders):
    people_orders.query(
        "SELECT p.name FROM people p LEFT JOIN orders o ON p.id = o.person_id "
        "WHERE o.amount IS NULL"
    )


def test_select_expression_with_alias(people_orders):
    result = people_orders.query("SELECT age * 2 AS double_age FROM people WHERE age IS NOT NULL")
    assert all(isinstance(r[0], int) for r in result)


# -- Errors -------------------------------------------------------------------


def test_unknown_table_raises(db: Database):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM nope")


def test_unknown_column_raises(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT nope FROM t")


def test_ambiguous_column_raises(db: Database):
    db.execute("CREATE TABLE a (x INTEGER)")
    db.execute("CREATE TABLE b (x INTEGER)")
    db.execute("INSERT INTO a VALUES (1)")
    db.execute("INSERT INTO b VALUES (1)")
    with pytest.raises(SQLError):
        db.execute("SELECT x FROM a JOIN b ON a.x = b.x")


def test_invalid_sql_raises(db: Database):
    with pytest.raises(SQLError):
        db.execute("SELECT FROM WHERE")


def test_unqualified_star_still_resolves_all_columns(people_orders):
    people_orders.query(
        "SELECT * FROM people p JOIN orders o ON p.id = o.person_id"
    )
