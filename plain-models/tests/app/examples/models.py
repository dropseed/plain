from plain import models


class Car(models.Model):
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["make", "model"], name="unique_make_model"),
        ]
