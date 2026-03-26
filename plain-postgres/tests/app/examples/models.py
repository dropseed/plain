from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types


@postgres.register_model
class Feature(postgres.Model):
    name: str = types.CharField(max_length=100)

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
    make: str = types.CharField(max_length=100)
    model: str = types.CharField(max_length=100)
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


@postgres.register_model
class DeleteParent(postgres.Model):
    name: str = types.CharField(max_length=100)

    query: postgres.QuerySet[DeleteParent] = postgres.QuerySet()

    # Explicit reverse relation - no more TYPE_CHECKING hacks!
    childcascade_set: types.ReverseForeignKey[ChildCascade] = types.ReverseForeignKey(
        to="ChildCascade", field="parent"
    )


@postgres.register_model
class ChildCascade(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.CASCADE
    )

    query: postgres.QuerySet[ChildCascade] = postgres.QuerySet()


@postgres.register_model
class ChildProtect(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.PROTECT
    )

    query: postgres.QuerySet[ChildProtect] = postgres.QuerySet()


@postgres.register_model
class ChildRestrict(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.RESTRICT
    )

    query: postgres.QuerySet[ChildRestrict] = postgres.QuerySet()


@postgres.register_model
class ChildSetNull(postgres.Model):
    parent: DeleteParent | None = types.ForeignKeyField(
        DeleteParent,
        on_delete=postgres.SET_NULL,
        allow_null=True,
    )
    parent_id: int | None

    query: postgres.QuerySet[ChildSetNull] = postgres.QuerySet()


@postgres.register_model
class ChildSetDefault(postgres.Model):
    def default_parent_id():
        return DeleteParent.query.get(name="default").id

    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent,
        on_delete=postgres.SET_DEFAULT,
        default=default_parent_id,
    )
    parent_id: int

    query: postgres.QuerySet[ChildSetDefault] = postgres.QuerySet()


@postgres.register_model
class ChildDoNothing(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.DO_NOTHING
    )

    query: postgres.QuerySet[ChildDoNothing] = postgres.QuerySet()


# Models for testing QuerySet assignment behavior
@postgres.register_model
class DefaultQuerySetModel(postgres.Model):
    """Model that uses the default objects QuerySet."""

    name: str = types.CharField(max_length=100)

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

    name: str = types.CharField(max_length=100)

    query = CustomQuerySet()


@postgres.register_model
class CustomSpecialQuerySetModel(postgres.Model):
    """Model with a custom special QuerySet."""

    name: str = types.CharField(max_length=100)

    query = CustomSpecialQuerySet()


# Test mixin pattern for field inheritance
class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at: datetime = types.CreatedAtField()
    updated_at: datetime = types.UpdatedAtField()


@postgres.register_model
class MixinTestModel(TimestampMixin, postgres.Model):
    """Model that inherits fields from a mixin."""

    name: str = types.CharField(max_length=100)

    query: postgres.QuerySet[MixinTestModel] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
    )


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: str = types.CharField(max_length=100)
    api_key: str = types.EncryptedTextField(max_length=200)
    notes: str = types.EncryptedTextField(required=False)
    config: dict = types.EncryptedJSONField(required=False, allow_null=True)

    query: postgres.QuerySet[SecretStore] = postgres.QuerySet()
