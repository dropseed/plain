from django import template

from ..permissions import can_impersonate_user as _can_impersonate_user

register = template.Library()


@register.filter
def can_impersonate_user(user, target_user):
    return _can_impersonate_user(user, target_user)
