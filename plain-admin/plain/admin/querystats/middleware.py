import json
import logging
import re
import threading

from plain.http import ResponseRedirect
from plain.json import PlainJSONEncoder
from plain.models import connection
from plain.runtime import settings
from plain.urls import reverse

from .core import QueryStats

try:
    try:
        import psycopg
    except ImportError:
        import psycopg2 as psycopg
except ImportError:
    psycopg = None

logger = logging.getLogger(__name__)
_local = threading.local()


class QueryStatsJSONEncoder(PlainJSONEncoder):
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            if psycopg and isinstance(obj, psycopg._json.Json):
                return obj.adapted
            else:
                raise


class QueryStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ignore_url_patterns = [
            re.compile(url) for url in settings.QUERYSTATS_IGNORE_URLS
        ]

    def should_ignore_request(self, request):
        for url in self.ignore_url_patterns:
            if url.match(request.path):
                return True

        return False

    def __call__(self, request):
        if request.GET.get("querystats") == "disable":
            return self.get_response(request)

        querystats = QueryStats(
            # Only want these if we're getting ready to show it
            include_tracebacks=request.GET.get("querystats") == "store"
        )

        with connection.execute_wrapper(querystats):
            # Have to wrap this first call so it is included in the querystats,
            # but we don't have to wrap everything else unless we are admin or debug
            is_admin = self.is_admin_request(request)

        if (settings.DEBUG or is_admin) and not self.should_ignore_request(request):
            # Persist it on the thread
            _local.querystats = querystats

            with connection.execute_wrapper(_local.querystats):
                response = self.get_response(request)

            if settings.DEBUG:
                # TODO logging settings
                logger.debug("Querystats: %s", _local.querystats)

            # Make current querystats available on the current page
            # by using the server timing API which can be parsed client-side
            response.headers["Server-Timing"] = _local.querystats.as_server_timing()

            if request.GET.get("querystats") == "store":
                request.session["querystats"] = json.dumps(
                    _local.querystats.as_context_dict(), cls=QueryStatsJSONEncoder
                )
                return ResponseRedirect(reverse("querystats:querystats"))

            del _local.querystats

            return response

        else:
            return self.get_response(request)

    @staticmethod
    def is_admin_request(request):
        if getattr(request, "impersonator", None):
            # Support for impersonation (still want the real admin user to see the querystats)
            return request.impersonator and request.impersonator.is_admin

        return hasattr(request, "user") and request.user and request.user.is_admin
