from plain import models


@models.register_model
class Car(models.Model):
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["make", "model"], name="unique_make_model"),
        ]


class UnregisteredModel(models.Model):
    pass


@models.register_model
class DeleteParent(models.Model):
    name = models.CharField(max_length=100)


@models.register_model
class ChildCascade(models.Model):
    parent = models.ForeignKey(DeleteParent, on_delete=models.CASCADE)


@models.register_model
class ChildProtect(models.Model):
    parent = models.ForeignKey(DeleteParent, on_delete=models.PROTECT)


@models.register_model
class ChildRestrict(models.Model):
    parent = models.ForeignKey(DeleteParent, on_delete=models.RESTRICT)


@models.register_model
class ChildSetNull(models.Model):
    parent = models.ForeignKey(
        DeleteParent,
        on_delete=models.SET_NULL,
        allow_null=True,
    )


@models.register_model
class ChildSetDefault(models.Model):
    def default_parent_id():
        return DeleteParent.objects.get(name="default").id

    parent = models.ForeignKey(
        DeleteParent,
        on_delete=models.SET_DEFAULT,
        default=default_parent_id,
    )


@models.register_model
class ChildDoNothing(models.Model):
    parent = models.ForeignKey(DeleteParent, on_delete=models.DO_NOTHING)
