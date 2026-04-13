from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types

from .delete import *  # noqa: F401,F403


@postgres.register_model
class Feature(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[Feature] = postgres.QuerySet()

    # Explicit reverse relation - no more TYPE_CHECKING hacks!
    cars: types.ReverseManyToMany[Car] = types.ReverseManyToMany(
        to="Car", field="features"
    )


@postgres.register_model
class CarFeature(postgres.Model):
    """Through model for Car-Feature many-to-many relationship."""

    car: Car = types.ForeignKeyField("Car", on_delete=postgres.CASCADE)
    car_id: int
    feature: Feature = types.ForeignKeyField(Feature, on_delete=postgres.CASCADE)
    feature_id: int

    query: postgres.QuerySet[CarFeature] = postgres.QuerySet()


@postgres.register_model
class Car(postgres.Model):
    make: str = types.TextField(max_length=100)
    model: str = types.TextField(max_length=100)
    features: types.ManyToManyManager[Feature] = types.ManyToManyField(
        Feature, through=CarFeature
    )

    query: postgres.QuerySet[Car] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["make", "model"], name="unique_make_model"
            ),
        ]
    )


class UnregisteredModel(postgres.Model):
    pass


# Models for testing QuerySet assignment behavior
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


# Test mixin pattern for field inheritance
class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)


@postgres.register_model
class MixinTestModel(TimestampMixin, postgres.Model):
    """Model that inherits fields from a mixin."""

    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[MixinTestModel] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
    )


@postgres.register_model
class TreeNode(postgres.Model):
    """Self-referential FK for testing convergence with circular references."""

    name: str = types.TextField(max_length=100)
    parent: TreeNode | None = types.ForeignKeyField(
        "self", on_delete=postgres.CASCADE, allow_null=True
    )
    parent_id: int | None

    query: postgres.QuerySet[TreeNode] = postgres.QuerySet()


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: str = types.TextField(max_length=100)
    api_key: str = types.EncryptedTextField(max_length=200)
    notes: str = types.EncryptedTextField(required=False)
    config: dict = types.EncryptedJSONField(required=False, allow_null=True)

    query: postgres.QuerySet[SecretStore] = postgres.QuerySet()
