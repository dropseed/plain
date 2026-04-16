from __future__ import annotations

from plain.postgres.forms import ModelForm

from .models.defaults import DBDefaultsExample
from .models.delete import ChildCascade
from .models.encrypted import SecretStore
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


class ChildCascadeForm(ModelForm):
    class Meta:
        model = ChildCascade
        fields = ("parent",)


class DBDefaultsExampleForm(ModelForm):
    """Includes DB-expression default fields so the test can confirm the
    form lets the user omit them and the database fills them in."""

    class Meta:
        model = DBDefaultsExample
        fields = ("name", "db_uuid", "created_at")


class SecretStoreForm(ModelForm):
    class Meta:
        model = SecretStore
        fields = ("name", "api_key", "notes", "config")
