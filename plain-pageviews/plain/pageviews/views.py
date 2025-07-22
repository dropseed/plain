import json

from plain.runtime import settings
from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin

from .models import Pageview


class TrackView(CsrfExemptViewMixin, View):
    def post(self):
        if getattr(self.request, "impersonator", None):
            # Don't track page views if we're impersonating a user
            return 200

        try:
            data = self.request.data
        except json.JSONDecodeError:
            return 400

        try:
            url = data["url"]
            title = data["title"]
            referrer = data["referrer"]
            timestamp = data["timestamp"]
        except KeyError:
            return 400

        if user := getattr(self.request, "user", None):
            user_id = user.id
        else:
            user_id = ""

        if session := getattr(self.request, "session", None):
            session_key = session.session_key or ""

            if settings.PAGEVIEWS_ASSOCIATE_ANONYMOUS_SESSIONS:
                if not user_id:
                    if not session_key:
                        # Make sure we have a key to use
                        session.create()
                        session_key = session.session_key

                    # The user hasn't logged in yet but might later. When they do log in,
                    # the session key itself will be cycled (session fixation attacks),
                    # so we'll store the anonymous session id in the data which will be preserved
                    # when the key cycles, then remove it immediately after.
                    session["pageviews_anonymous_session_key"] = session_key
                elif user_id and "pageviews_anonymous_session_key" in session:
                    # Associate the previously anonymous pageviews with the user
                    Pageview.objects.filter(
                        user_id="",
                        session_key=session["pageviews_anonymous_session_key"],
                    ).update(user_id=user_id)

                    # Remove it so we don't keep trying to associate it
                    del session["pageviews_anonymous_session_key"]
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
