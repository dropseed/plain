from datetime import datetime

from plain import models
from plain.models import types


@models.register_model
class Car(models.Model):
    make: str = types.CharField(max_length=100)
    model: str = types.CharField(max_length=100)

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(fields=["make", "model"], name="unique_make_model"),
        ]
    )


class UnregisteredModel(models.Model):
    pass


@models.register_model
class DeleteParent(models.Model):
    name: str = types.CharField(max_length=100)


@models.register_model
class ChildCascade(models.Model):
    parent: DeleteParent = types.ForeignKey(
        DeleteParent, on_delete=models.CASCADE, related_name="childcascade_set"
    )


@models.register_model
class ChildProtect(models.Model):
    parent: DeleteParent = types.ForeignKey(DeleteParent, on_delete=models.PROTECT)


@models.register_model
class ChildRestrict(models.Model):
    parent: DeleteParent = types.ForeignKey(DeleteParent, on_delete=models.RESTRICT)


@models.register_model
class ChildSetNull(models.Model):
    parent: DeleteParent | None = types.ForeignKey(
        DeleteParent,
        on_delete=models.SET_NULL,
        allow_null=True,
    )


@models.register_model
class ChildSetDefault(models.Model):
    def default_parent_id():
        return DeleteParent.query.get(name="default").id

    parent: DeleteParent = types.ForeignKey(
        DeleteParent,
        on_delete=models.SET_DEFAULT,
        default=default_parent_id,
    )


@models.register_model
class ChildDoNothing(models.Model):
    parent: DeleteParent = types.ForeignKey(DeleteParent, on_delete=models.DO_NOTHING)


# Models for testing QuerySet assignment behavior
@models.register_model
class DefaultQuerySetModel(models.Model):
    """Model that uses the default objects QuerySet."""

    name: str = types.CharField(max_length=100)


class CustomQuerySet(models.QuerySet):
    def get_custom(self):
        return self.filter(name__startswith="custom")


class CustomSpecialQuerySet(models.QuerySet):
    def get_custom_qs(self):
        return self.filter(name__startswith="custom")


@models.register_model
class CustomQuerySetModel(models.Model):
    """Model with a custom QuerySet."""

    name: str = types.CharField(max_length=100)

    query = CustomQuerySet()


@models.register_model
class CustomSpecialQuerySetModel(models.Model):
    """Model with a custom special QuerySet."""

    name: str = types.CharField(max_length=100)

    query = CustomSpecialQuerySet()


# Test mixin pattern for field inheritance
class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)


@models.register_model
class MixinTestModel(TimestampMixin, models.Model):
    """Model that inherits fields from a mixin."""

    name: str = types.CharField(max_length=100)

    model_options = models.Options(
        ordering=["-created_at"],
    )
