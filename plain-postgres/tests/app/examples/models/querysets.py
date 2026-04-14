from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class DefaultQuerySetModel(postgres.Model):
    """Model that uses the default objects QuerySet."""

    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[DefaultQuerySetModel] = postgres.QuerySet()


class CustomQuerySet(postgres.QuerySet):
    def get_custom(self):
        return self.filter(name__startswith="custom")


class CustomSpecialQuerySet(postgres.QuerySet):
    def get_custom_qs(self):
        return self.filter(name__startswith="custom")


@postgres.register_model
class CustomQuerySetModel(postgres.Model):
    """Model with a custom QuerySet."""

    name: str = types.TextField(max_length=100)

    query = CustomQuerySet()


@postgres.register_model
class CustomSpecialQuerySetModel(postgres.Model):
    """Model with a custom special QuerySet."""

    name: str = types.TextField(max_length=100)

    query = CustomSpecialQuerySet()
