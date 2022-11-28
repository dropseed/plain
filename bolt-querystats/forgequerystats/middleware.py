import json
import logging
import threading

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.http import HttpResponseRedirect
from django.template.loader import select_template

from .core import QueryStats

logger = logging.getLogger(__name__)
_local = threading.local()


class QueryStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.GET.get("querystats") == "disable":
            return self.get_response(request)

        querystats = QueryStats(
            # Only want these if we're getting ready to show it
            include_tracebacks=request.GET.get("querystats")
            == "store"
        )

        with connection.execute_wrapper(querystats):
            # Have to wrap this first call so it is included in the querystats,
            # but we don't have to wrap everything else unless we are staff or debug
            is_staff = self.is_staff_request(request)

        if settings.DEBUG or is_staff:
            # Persist it on the thread
            _local.querystats = querystats

            with connection.execute_wrapper(_local.querystats):
                response = self.get_response(request)

            if settings.DEBUG:
                # TODO logging settings
                logger.debug("Querystats: %s", _local.querystats)

            # Make current querystats available on the current page
            # by using the server timing API which can be parsed client-side
            response["Server-Timing"] = _local.querystats.as_server_timing()

            if request.GET.get("querystats") == "store":
                request.session["querystats"] = json.dumps(
                    _local.querystats.as_context_dict(), cls=DjangoJSONEncoder
                )
                return HttpResponseRedirect(
                    request.get_full_path().replace(
                        "querystats=store", "querystats=show"
                    )
                )

            del _local.querystats

            return response

        else:
            return self.get_response(request)

    @staticmethod
    def is_staff_request(request):
        if getattr(request, "impersonator", None):
            # Support for impersonation (still want the real staff user to see the querystats)
            return (
                request.impersonator.is_authenticated and request.impersonator.is_staff
            )

        return (
            hasattr(request, "user")
            and request.user.is_authenticated
            and request.user.is_staff
        )

    def process_template_response(self, request, response):
        # Template hasn't been rendered yet, so we can't include querystats themselves
        # unless we're pulling the previous page stats from the session storage
        if response.context_data is not None and hasattr(_local, "querystats") and self.is_staff_request(request):
            response.context_data["querystats_enabled"] = True

            # Load the previous querystats from the session and display them
            if request.GET.get("querystats") == "show":
                stored_querystats = request.session.get(
                    "querystats"
                )  # Not popping so page can be reloaded
                if stored_querystats:
                    # dates won't come back as Python dates...
                    stored_querystats = json.loads(stored_querystats)
                    response.context_data["querystats"] = stored_querystats

                # Extend the original template and overlay our querystats on top
                response.context_data["querystats_extend_template"] = select_template(
                    response.template_name
                )

                # Additional context for the view
                response.context_data[
                    "querystats_resolver_match"
                ] = request.resolver_match

                # Show full template debug info
                response.context_data[
                    "querystats_template_name"
                ] = response.template_name

                response.template_name = "querystats/querystats.html"

        return response
