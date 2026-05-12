from datetime import timedelta

from plain.paginator import Paginator
from plain.urls import absolute_url, reverse, reverse_absolute
from plain.utils import timezone

default_globals = {
    "url": reverse,  # Alias for reverse
    "reverse": reverse,
    "reverse_absolute": reverse_absolute,
    "absolute_url": absolute_url,
    "Paginator": Paginator,
    "now": timezone.now,
    "timedelta": timedelta,
    "localtime": timezone.localtime,
}
