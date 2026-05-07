from __future__ import annotations

from app.api import APIRouter

from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("api/", APIRouter),
    ]
