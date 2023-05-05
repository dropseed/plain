import sqlparse


def pretty_print_sql(sql):
    return sqlparse.format(sql, reindent=True, keyword_case="upper")
