from __future__ import annotations

from plain.http import RedirectResponse, Response
from plain.urls import reverse
from plain.views import View

from app.jobs import ExampleJob


class RunExampleJobView(View):
    def post(self) -> Response:
        ExampleJob().run_in_worker()
        return RedirectResponse(reverse("index") + "?queued=ExampleJob")
