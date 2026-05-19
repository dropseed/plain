from __future__ import annotations

from plain.postgres.forms import ModelForm, model_field

from .models import SupportFormEntry


class SupportForm(ModelForm):
    name = model_field(SupportFormEntry.name)
    email = model_field(SupportFormEntry.email)
    message = model_field(SupportFormEntry.message)
