from boltquerystats.sql import pretty_print_sql


def test_pretty_print_sql():
    sql = "SELECT * FROM foo WHERE bar = 'baz' ORDER BY baz LIMIT 10"
    assert pretty_print_sql(sql) == (
        "SELECT *\nFROM foo\nWHERE bar = 'baz'\nORDER BY baz\nLIMIT 10"
    )
