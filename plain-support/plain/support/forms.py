from __future__ import annotations

from plain.forms import Field
from plain.postgres.forms import ModelForm, model_field

from .models import SupportFormEntry


class SupportForm(ModelForm):
    model = SupportFormEntry

    name: Field[str] = model_field()
    email: Field[str] = model_field()
    message: Field[str] = model_field()
