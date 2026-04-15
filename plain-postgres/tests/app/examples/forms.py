from __future__ import annotations

from plain.postgres.forms import ModelForm

from .models.forms import FormsExample


class FormsExampleForm(ModelForm):
    class Meta:
        model = FormsExample
        fields = (
            "name",
            "status",
            "note",
            "count",
            "ratio",
            "amount",
            "is_active",
            "event_date",
            "event_time",
            "event_datetime",
            "duration",
            "external_id",
        )
