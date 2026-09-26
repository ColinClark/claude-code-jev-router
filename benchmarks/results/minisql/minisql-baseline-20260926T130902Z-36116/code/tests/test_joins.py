from .conftest import assert_matches_sqlite

SETUP = [
    "CREATE TABLE dept (id INTEGER, name TEXT)",
    "CREATE TABLE emp (id INTEGER, dept_id INTEGER, name TEXT, salary REAL)",
    "INSERT INTO dept VALUES (1, 'Eng'), (2, 'Sales'), (3, 'HR')",
    """INSERT INTO emp VALUES
        (1, 1, 'Alice', 100.0),
        (2, 1, 'Bob', 200.0),
        (3, 2, 'Carl', 150.0),
        (4, NULL, 'Dana', 50.0)
    """,
]


def test_inner_join():
    assert_matches_sqlite(
        SETUP,
        "SELECT emp.name, dept.name FROM emp JOIN dept ON emp.dept_id = dept.id ORDER BY emp.id",
    )


def test_inner_join_explicit_keyword():
    assert_matches_sqlite(
        SETUP,
        "SELECT emp.name, dept.name FROM emp INNER JOIN dept ON emp.dept_id = dept.id "
        "ORDER BY emp.id",
    )


def test_left_join_keeps_unmatched_rows():
    assert_matches_sqlite(
        SETUP,
        "SELECT emp.name, dept.name FROM emp LEFT JOIN dept ON emp.dept_id = dept.id "
        "ORDER BY emp.id",
    )


def test_left_outer_join_keyword():
    assert_matches_sqlite(
        SETUP,
        "SELECT emp.name, dept.name FROM emp LEFT OUTER JOIN dept ON emp.dept_id = dept.id "
        "ORDER BY emp.id",
    )


def test_left_join_no_matches_for_dept_with_no_employees():
    assert_matches_sqlite(
        SETUP,
        "SELECT dept.name, emp.name FROM dept LEFT JOIN emp ON dept.id = emp.dept_id "
        "ORDER BY dept.name, emp.name",
    )


def test_join_with_table_aliases():
    assert_matches_sqlite(
        SETUP,
        "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    )


def test_multiple_joins():
    setup = SETUP + [
        "CREATE TABLE loc (dept_id INTEGER, city TEXT)",
        "INSERT INTO loc VALUES (1, 'NYC'), (2, 'LA')",
    ]
    assert_matches_sqlite(
        setup,
        "SELECT e.name, d.name, l.city FROM emp e "
        "JOIN dept d ON e.dept_id = d.id "
        "LEFT JOIN loc l ON d.id = l.dept_id "
        "ORDER BY e.id",
    )


def test_join_with_where_filter():
    assert_matches_sqlite(
        SETUP,
        "SELECT e.name FROM emp e JOIN dept d ON e.dept_id = d.id WHERE d.name = 'Eng' "
        "ORDER BY e.id",
    )


def test_select_star_across_join():
    assert_matches_sqlite(
        SETUP,
        "SELECT * FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    )


def test_select_alias_star():
    assert_matches_sqlite(
        SETUP,
        "SELECT e.* FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    )
