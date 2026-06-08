from __future__ import annotations

from typing import ClassVar

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class Tag(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)

    widgets: ClassVar[types.ReverseManyToMany[Widget]] = types.ReverseManyToMany(
        to="Widget", field="tags"
    )


@postgres.register_model
class WidgetTag(postgres.Model):
    """Through model for Widget-Tag many-to-many relationship."""

    widget: Widget = types.ForeignKeyField("Widget", on_delete=postgres.CASCADE)
    tag: Field[Tag] = types.ForeignKeyField(Tag, on_delete=postgres.CASCADE)


@postgres.register_model
class Widget(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    size: Field[str] = types.TextField(max_length=100)
    tags: types.ManyToManyManager[Tag] = types.ManyToManyField(Tag, through=WidgetTag)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name", "size"], name="unique_widget_name_size"
            ),
        ]
    )
