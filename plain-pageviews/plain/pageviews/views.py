import json

from plain.views import View

from .models import Pageview


class TrackView(View):
    def post(self):
        try:
            data = self.request.data
        except json.JSONDecodeError:
            return 400

        try:
            pageview = Pageview.create_from_request(
                self.request,
                url=data["url"],
                title=data["title"],
                referrer=data["referrer"],
                timestamp=data["timestamp"],
            )
        except KeyError:
            return 400

        if pageview is None:
            return 200

        return 201
