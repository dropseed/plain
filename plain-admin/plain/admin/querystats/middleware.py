import json
import logging
import re

from plain.json import PlainJSONEncoder
from plain.models import connection
from plain.runtime import settings

from .core import QueryStats

try:
    import psycopg
except ImportError:
    psycopg = None

logger = logging.getLogger(__name__)


class QueryStatsJSONEncoder(PlainJSONEncoder):
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            print(type(obj))
            if psycopg and isinstance(obj, psycopg.types.json.Json):
                return obj.obj
            elif psycopg and isinstance(obj, psycopg.types.json.Jsonb):
                return obj.obj
            else:
                raise


class QueryStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ignore_url_patterns = [
            re.compile(url) for url in settings.ADMIN_QUERYSTATS_IGNORE_URLS
        ]

    def should_ignore_request(self, request):
        for url in self.ignore_url_patterns:
            if url.match(request.path):
                return True

        return False

    def __call__(self, request):
        """
        Enables querystats for the current request.

        If DEBUG or an admin, then Server-Timing headers are always added to the response.
        Full querystats are only stored in the session if they are manually enabled.
        """

        if self.should_ignore_request(request):
            return self.get_response(request)

        def is_tracking():
            return "querystats" in request.session

        querystats = QueryStats(include_tracebacks=is_tracking())

        with connection.execute_wrapper(querystats):
            is_admin = self.is_admin_request(request)

        if settings.DEBUG or is_admin:
            with connection.execute_wrapper(querystats):
                response = self.get_response(request)

            if settings.DEBUG:
                # TODO logging settings
                logger.debug("Querystats: %s", querystats)

            # Make current querystats available on the current page
            # by using the server timing API which can be parsed client-side
            response.headers["Server-Timing"] = querystats.as_server_timing()

            if is_tracking() and querystats.num_queries > 0:
                request.session["querystats"][request.unique_id] = json.dumps(
                    querystats.as_context_dict(request), cls=QueryStatsJSONEncoder
                )

                # Keep 30 requests max, in case it is left on by accident
                if len(request.session["querystats"]) > 30:
                    del request.session["querystats"][
                        list(request.session["querystats"])[0]
                    ]

                # Did a deeper modification to the session dict...
                request.session.modified = True

            return response

        else:
            return self.get_response(request)

    @staticmethod
    def is_admin_request(request):
        if getattr(request, "impersonator", None):
            # Support for impersonation (still want the real admin user to see the querystats)
            return request.impersonator and request.impersonator.is_admin

        return hasattr(request, "user") and request.user and request.user.is_admin
