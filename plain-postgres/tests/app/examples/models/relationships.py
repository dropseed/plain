from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class Tag(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[Tag] = postgres.QuerySet()

    widgets: types.ReverseManyToMany[Widget] = types.ReverseManyToMany(
        to="Widget", field="tags"
    )


@postgres.register_model
class WidgetTag(postgres.Model):
    """Through model for Widget-Tag many-to-many relationship."""

    widget: Widget = types.ForeignKeyField("Widget", on_delete=postgres.CASCADE)
    widget_id: int
    tag: Tag = types.ForeignKeyField(Tag, on_delete=postgres.CASCADE)
    tag_id: int

    query: postgres.QuerySet[WidgetTag] = postgres.QuerySet()


@postgres.register_model
class Widget(postgres.Model):
    name: str = types.TextField(max_length=100)
    size: str = types.TextField(max_length=100)
    tags: types.ManyToManyManager[Tag] = types.ManyToManyField(Tag, through=WidgetTag)

    query: postgres.QuerySet[Widget] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name", "size"], name="unique_widget_name_size"
            ),
        ]
    )
