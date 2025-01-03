import json

from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin

from .models import Pageview


class TrackView(CsrfExemptViewMixin, View):
    def post(self):
        if hasattr(self.request, "impersonator"):
            # Don't track page views if we're impersonating a user
            return 200

        data = json.loads(self.request.body)

        url = data["url"]
        title = data["title"]
        referrer = data["referrer"]
        timestamp = data["timestamp"]

        if hasattr(self.request, "user"):
            user_id = self.request.user.pk
        else:
            user_id = ""

        if hasattr(self.request, "session"):
            session_key = self.request.session.session_key
        else:
            session_key = None

        Pageview.objects.create(
            user_id=user_id,
            session_key=session_key,
            url=url,
            title=title,
            referrer=referrer,
            timestamp=timestamp,
        )

        return 201
