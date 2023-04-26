from forgequerystats.sql import pretty_print_sql


def test_pretty_print_sql():
    sql = "SELECT * FROM foo WHERE bar = 'baz' ORDER BY baz LIMIT 10"
    assert pretty_print_sql(sql) == (
        "SELECT *\n" "FROM foo\n" "WHERE bar = 'baz'\n" "ORDER BY baz\n" "LIMIT 10"
    )
