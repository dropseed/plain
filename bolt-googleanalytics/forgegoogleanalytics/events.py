import datetime
import logging
import uuid
from typing import List

import requests
from django.conf import settings as django_settings

from . import settings
from .utils import user_id, user_id_from_request

logger = logging.getLogger(__name__)


class GoogleAnalyticsEvent(object):
    def __init__(self, *, name: str, params: dict = {}):
        self.name = name
        # For suggested event names and params, see:
        # https://ga-dev-tools.web.app/ga4/event-builder/
        #
        # To show in realtime reports (and more?) need session_id and engagement_time_msec
        # https://developers.google.com/analytics/devguides/collection/protocol/ga4/sending-events?client_type=gtag#required_parameters
        self.params = params

    def as_dict(self):
        return {
            "name": self.name,
            "params": self.params,
        }

    def send(self, **kwargs):
        send_events(events=[self], **kwargs)


def send_events(
    *, events: List[GoogleAnalyticsEvent], user=None, request=None, validate=None
) -> None:
    if not settings.GOOGLEANALYTICS_MEASUREMENT_ID():
        # Return silently - not expected to be tracking anything
        return

    if not settings.GOOGLEANALYTICS_API_SECRET():
        # Measurement ID is set, so we should expect the API secret
        # if we're trying to send an event
        raise ValueError("GOOGLEANALYTICS_API_SECRET is not set")

    # Use settings.DEBUG as the default for this
    validating = validate is True or (validate is None and django_settings.DEBUG)

    if validating:
        # Validate events
        url = "https://www.google-analytics.com/debug/mp/collect"
    else:
        url = "https://www.google-analytics.com/mp/collect"

    response = requests.post(
        url,
        params={
            "api_secret": settings.GOOGLEANALYTICS_API_SECRET(),
            "measurement_id": settings.GOOGLEANALYTICS_MEASUREMENT_ID(),
        },
        json={
            "client_id": str(uuid.uuid4()),
            "user_id": user_id(user) if user else user_id_from_request(request),
            "events": [event.as_dict() for event in events],
        },
    )

    try:
        # https://developers.google.com/analytics/devguides/collection/protocol/ga4/validating-events?client_type=gtag
        # Won't actually return HTTP error codes, so you have to validate your events before sending
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.exception("Failed to send Google Analytics events")

    if validating and response.json().get("validationMessages", []):
        raise ValueError("Google Analytics events are invalid:\n", response.json())
