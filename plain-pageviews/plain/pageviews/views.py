import json

from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin

from .models import Pageview


class TrackView(CsrfExemptViewMixin, View):
    def post(self):
        if getattr(self.request, "impersonator", None):
            # Don't track page views if we're impersonating a user
            return 200

        data = json.loads(self.request.body)

        url = data["url"]
        title = data["title"]
        referrer = data["referrer"]
        timestamp = data["timestamp"]

        if user := getattr(self.request, "user", None):
            user_id = user.pk
        else:
            user_id = ""

        if session := getattr(self.request, "session", None):
            session_key = session.session_key or ""
        else:
            session_key = ""

        Pageview.objects.create(
            user_id=user_id,
            session_key=session_key,
            url=url,
            title=title,
            referrer=referrer,
            timestamp=timestamp,
        )

        return 201
