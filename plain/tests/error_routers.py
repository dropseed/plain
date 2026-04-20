"""Views and routers for test_error_responses.py."""

from __future__ import annotations

from plain.http import ForbiddenError403, HTTPException, NotFoundError404
from plain.urls import Router, path
from plain.views import TemplateView, View


class PaymentRequiredError402(HTTPException):
    status_code = 402


class PlainViewRaises404(View):
    def get(self):
        raise NotFoundError404("plain view says not found")


class PlainViewRaises500(View):
    def get(self):
        raise RuntimeError("plain view boom")


class PlainViewRaisesCustomHTTPException(View):
    def get(self):
        raise PaymentRequiredError402("pay up")


class TemplateViewRaises404(TemplateView):
    def get(self):
        raise NotFoundError404("template view says not found")


class TemplateViewRaises403(TemplateView):
    def get(self):
        raise ForbiddenError403("template view says forbidden")


class TemplateViewRaises500(TemplateView):
    def get(self):
        raise RuntimeError("template view boom")


class ErrorRouter(Router):
    namespace = ""
    urls = [
        path("plain-404/", PlainViewRaises404, name="plain-404"),
        path("plain-500/", PlainViewRaises500, name="plain-500"),
        path("plain-402/", PlainViewRaisesCustomHTTPException, name="plain-402"),
        path("template-404/", TemplateViewRaises404, name="template-404"),
        path("template-403/", TemplateViewRaises403, name="template-403"),
        path("template-500/", TemplateViewRaises500, name="template-500"),
    ]
