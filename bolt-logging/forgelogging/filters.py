import logging
from django.conf import settings


class ExcludeCommonURLsFilter(logging.Filter):
    def __init__(self):
        self.exclude_urls = [
            "/admin/jsi18n/",  # could be customized...
            "/favicon.ico",
        ]

        if settings.STATIC_URL:
            self.exclude_urls.append(settings.STATIC_URL)

        super().__init__()

    def filter(self, record):
        message = record.getMessage()

        if message.startswith('"GET /'):  # Only check them all if it's a GET
            for url in self.exclude_urls:
                if message.startswith(f'"GET {url}'):
                    return False

        return True
