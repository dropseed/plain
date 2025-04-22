import datetime
import time
import traceback
from collections import Counter

import sqlparse

from plain.utils.functional import cached_property

IGNORE_STACK_FILES = [
    "threading",
    "concurrent/futures",
    "functools.py",
    "socketserver",
    "wsgiref",
    "gunicorn",
    "whitenoise",
    "sentry_sdk",
    "querystats/core",
    "plain/template/base",
    "plain/models",
    "plain/internal",
]


def pretty_print_sql(sql):
    return sqlparse.format(sql, reindent=True, keyword_case="upper")


def get_stack():
    return "".join(tidy_stack(traceback.format_stack()))


def tidy_stack(stack):
    lines = []

    skip_next = False

    for line in stack:
        if skip_next:
            skip_next = False
            continue

        if line.startswith('  File "') and any(
            ignore in line for ignore in IGNORE_STACK_FILES
        ):
            skip_next = True
            continue

        lines.append(line)

    return lines


class QueryStats:
    def __init__(self, include_tracebacks):
        self.queries = []
        self.include_tracebacks = include_tracebacks

    def __str__(self):
        s = f"{self.num_queries} queries in {self.total_time_display}"
        if self.duplicate_queries:
            s += f" ({self.num_duplicate_queries} duplicates)"
        return s

    def __call__(self, execute, sql, params, many, context):
        current_query = {"sql": sql, "params": params, "many": many}
        start = time.monotonic()

        result = execute(sql, params, many, context)

        if self.include_tracebacks:
            current_query["tb"] = get_stack()

        # if many, then X times is len(params)

        # current_query["result"] = result

        current_query["duration"] = time.monotonic() - start

        self.queries.append(current_query)
        return result

    @cached_property
    def total_time(self):
        return sum(q["duration"] for q in self.queries)

    @staticmethod
    def get_time_display(seconds):
        if seconds < 0.01:
            return f"{seconds * 1000:.0f} ms"
        return f"{seconds:.2f} seconds"

    @cached_property
    def total_time_display(self):
        return self.get_time_display(self.total_time)

    @cached_property
    def num_queries(self):
        return len(self.queries)

    # @cached_property
    # def models(self):
    #     # parse table names from self.queries sql
    #     table_names = [x for x in [q['sql'].split(' ')[2] for q in self.queries] if x]
    #     models = connection.introspection.installed_models(table_names)
    #     return models

    @cached_property
    def duplicate_queries(self):
        sqls = [q["sql"] for q in self.queries]
        duplicates = {k: v for k, v in Counter(sqls).items() if v > 1}
        return duplicates

    @cached_property
    def num_duplicate_queries(self):
        # Count the number of "excess" queries by getting how many there
        # are minus the initial one (and potentially only one required)
        return sum(self.duplicate_queries.values()) - len(self.duplicate_queries)

    def as_summary_dict(self):
        return {
            "summary": str(self),
            "total_time": self.total_time,
            "num_queries": self.num_queries,
            "num_duplicate_queries": self.num_duplicate_queries,
        }

    def as_context_dict(self, request):
        # If we don't create a dict, the instance of this class
        # is lost before we can use it in the template
        for query in self.queries:
            # Add some useful display info
            query["duration_display"] = self.get_time_display(query["duration"])
            query["sql_display"] = pretty_print_sql(query["sql"])
            duplicates = self.duplicate_queries.get(query["sql"], 0)
            if duplicates:
                query["duplicate_count"] = duplicates

        return {
            **self.as_summary_dict(),
            "request": {
                "path": request.path,
                "method": request.method,
                "unique_id": request.unique_id,
            },
            "timestamp": datetime.datetime.now().isoformat(),
            "total_time_display": self.total_time_display,
            "queries": self.queries,
        }

    def as_server_timing(self):
        duration = self.total_time * 1000  # put in ms
        duration = round(duration, 2)
        description = str(self)
        return f'querystats;dur={duration};desc="{description}"'
