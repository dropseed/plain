from __future__ import annotations

from typing import Any

from plain.runtime import settings


def get_react_settings() -> dict[str, Any]:
    """
    Get React-specific settings from plain settings.

    Configure in your app settings:

        REACT = {
            "title": "My App",
            "root_id": "app",
            "head": '<link rel="stylesheet" href="/assets/app.css">',
            "vite_dev_url": "http://localhost:5173",
        }
    """
    return getattr(settings, "REACT", {})
