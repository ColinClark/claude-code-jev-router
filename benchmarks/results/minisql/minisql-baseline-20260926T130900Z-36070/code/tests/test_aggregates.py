import pytest


@pytest.fixture
def sales(dual):
    dual.run("CREATE TABLE sales (region TEXT, amount INTEGER, rep TEXT)")
    dual.run(
        "INSERT INTO sales (region, amount, rep) VALUES "
        "('east', 10, 'a'), ('east', 20, 'b'), ('west', 5, 'a'), "
        "('west', NULL, 'c'), ('east', 10, 'a')"
    )
    return dual


def test_count_star_no_group(sales):
    sales.query("SELECT COUNT(*) FROM sales", ordered=True)


def test_count_expr_ignores_null(sales):
    sales.query("SELECT COUNT(amount) FROM sales", ordered=True)


def test_count_distinct(sales):
    sales.query("SELECT COUNT(DISTINCT amount) FROM sales", ordered=True)


def test_sum_avg_min_max(sales):
    sales.query(
        "SELECT SUM(amount), AVG(amount), MIN(amount), MAX(amount) FROM sales",
        ordered=True,
    )


def test_aggregates_on_empty_table(dual):
    dual.run("CREATE TABLE empty_t (a INTEGER)")
    dual.query(
        "SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a) FROM empty_t",
        ordered=True,
    )


def test_group_by_single_column(sales):
    sales.query(
        "SELECT region, SUM(amount), COUNT(*) FROM sales GROUP BY region"
    )


def test_group_by_multiple_columns(sales):
    sales.query(
        "SELECT region, rep, SUM(amount) FROM sales GROUP BY region, rep"
    )


def test_group_by_with_having(sales):
    sales.query(
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region HAVING SUM(amount) > 15"
    )


def test_group_by_with_having_count(sales):
    sales.query(
        "SELECT region, COUNT(*) AS c FROM sales GROUP BY region HAVING COUNT(*) > 1"
    )


def test_group_by_order_by_aggregate(sales):
    sales.query(
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region ORDER BY total DESC",
        ordered=True,
    )


def test_group_by_order_by_aggregate_not_selected(sales):
    sales.query(
        "SELECT region FROM sales GROUP BY region ORDER BY COUNT(*) DESC, region",
        ordered=True,
    )


def test_where_before_group_by(sales):
    sales.query(
        "SELECT region, SUM(amount) FROM sales WHERE rep = 'a' GROUP BY region"
    )


def test_sum_distinct(sales):
    sales.query("SELECT region, SUM(DISTINCT amount) FROM sales GROUP BY region")
