from __future__ import annotations

from app.jobs import ExampleJob
from plain.http import RedirectResponse, Response
from plain.urls import reverse
from plain.views import View


class RunExampleJobView(View):
    def post(self) -> Response:
        ExampleJob().run_in_worker()
        return RedirectResponse(reverse("index") + "?queued=ExampleJob")
