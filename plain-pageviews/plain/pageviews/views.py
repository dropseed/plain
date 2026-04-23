from plain.http import Response
from plain.views import View

from .models import Pageview


class TrackView(View):
    def post(self) -> Response:
        data = self.request.json_data

        try:
            pageview = Pageview.create_from_request(
                self.request,
                url=data["url"],
                title=data["title"],
                referrer=data["referrer"],
                timestamp=data["timestamp"],
            )
        except KeyError:
            return Response(status_code=400)

        if pageview is None:
            return Response(status_code=200)

        return Response(status_code=201)
