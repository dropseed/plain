from __future__ import annotations

from plain.forms import Form, types


class LoginLinkForm(Form):
    email = types.EmailField()
    next = types.TextField(required=False)
