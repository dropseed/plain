from __future__ import annotations

from typing import ClassVar

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class DefaultQuerySetModel(postgres.Model):
    """Model that uses the default objects QuerySet."""

    name: Field[str] = types.TextField(max_length=100)


class CustomQuerySet(postgres.QuerySet):
    def get_custom(self):
        return self.filter(name__startswith="custom")


class CustomSpecialQuerySet(postgres.QuerySet):
    def get_custom_qs(self):
        return self.filter(name__startswith="custom")


@postgres.register_model
class CustomQuerySetModel(postgres.Model):
    """Model with a custom QuerySet."""

    name: Field[str] = types.TextField(max_length=100)

    query: ClassVar[CustomQuerySet] = CustomQuerySet()


@postgres.register_model
class CustomSpecialQuerySetModel(postgres.Model):
    """Model with a custom special QuerySet."""

    name: Field[str] = types.TextField(max_length=100)

    query: ClassVar[CustomSpecialQuerySet] = CustomSpecialQuerySet()
