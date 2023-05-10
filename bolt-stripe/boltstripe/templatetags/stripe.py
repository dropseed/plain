import datetime

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def epoch_to_datetime(value):
    dt = datetime.datetime.utcfromtimestamp(value)
    return timezone.make_aware(dt, timezone.get_current_timezone())


@register.filter
def decimal_to_dollars(value, trunc_int=True):
    if not value:
        return value

    dollars = value / 100.00

    if trunc_int and dollars.is_integer():
        # remove the decimals for friendlier formatting
        dollars = int(dollars)

    return dollars
