"""Public contract — `ModelForm`, `model_field`, and the ORM write functions.

Drives the model-form API directly against models (no views, no HTTP), so it
stays independent of any app's view layer. Covers what only this layer proves:
`model_field(Model.column)` derivation across field kinds, `validate()`, and
`create_from()` / `update_from()` including the many-to-many round-trip.
"""

from __future__ import annotations

import pytest
from app.examples.models.defaults import DBDefaultsExample
from app.examples.models.forms import FormsExample
from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.forms import fields as form_fields
from plain.forms import types
from plain.postgres.forms import (
    ModelChoiceField,
    ModelForm,
    ModelMultipleChoiceField,
    create_from,
    model_field,
    update_from,
)


class WidgetForm(ModelForm):
    name = model_field(Widget.name)
    size = model_field(Widget.size)
    tags = model_field(Widget.tags)


class TestModelFieldDerivation:
    """`model_field(Model.column)` copies the column into a form field —
    including unwrapping the FK/M2M forward descriptors."""

    def test_scalar_column_becomes_a_plain_field(self):
        assert isinstance(WidgetForm.fields()["name"], form_fields.TextField)

    def test_m2m_column_becomes_a_multiple_choice_field(self):
        assert isinstance(WidgetForm.fields()["tags"], ModelMultipleChoiceField)

    def test_foreign_key_column_becomes_a_model_choice_field(self):
        class WidgetTagForm(ModelForm):
            widget = model_field(WidgetTag.widget)
            tag = model_field(WidgetTag.tag)

        assert isinstance(WidgetTagForm.fields()["widget"], ModelChoiceField)
        assert isinstance(WidgetTagForm.fields()["tag"], ModelChoiceField)

    def test_choice_and_boolean_columns(self):
        class FormsForm(ModelForm):
            status = model_field(FormsExample.status)
            is_active = model_field(FormsExample.is_active)

        fields = FormsForm.fields()
        assert isinstance(fields["status"], form_fields.TypedChoiceField)
        assert isinstance(fields["is_active"], form_fields.BooleanField)


class TestValidate:
    def test_success_is_a_typed_instance(self):
        result = WidgetForm.validate({"name": "Sprocket", "size": "L"})
        assert result
        assert result.name == "Sprocket"
        assert result.size == "L"

    def test_missing_required_field_is_rejected(self):
        result = WidgetForm.validate({"name": "Sprocket"})  # size omitted
        assert not result
        assert any(e.field == "size" and e.code == "required" for e in result.errors)


class TestCreateFrom:
    def test_creates_and_saves_a_row(self, db):
        result = WidgetForm.validate({"name": "Cog", "size": "S"})
        assert result
        widget = create_from(Widget, result)
        assert widget.id is not None
        assert Widget.query.get(id=widget.id).name == "Cog"

    def test_extra_kwargs_populate_columns_the_form_omits(self, db):
        class NameOnlyForm(ModelForm):
            name = model_field(Widget.name)

        result = NameOnlyForm.validate({"name": "Bolt"})
        assert result
        widget = create_from(Widget, result, size="M")
        assert (widget.name, widget.size) == ("Bolt", "M")

    def test_m2m_is_assigned_after_the_insert(self, db):
        red = Tag.query.create(name="red")
        blue = Tag.query.create(name="blue")
        result = WidgetForm.validate(
            {"name": "Painted", "size": "L", "tags": [red.id, blue.id]}
        )
        assert result
        widget = create_from(Widget, result)
        assert set(widget.tags.query) == {red, blue}


class TestUpdateFrom:
    def test_writes_onto_an_existing_row(self, db):
        widget = Widget.query.create(name="Old", size="S")
        result = WidgetForm.validate({"name": "New", "size": "S"})
        assert result
        update_from(widget, result)
        assert Widget.query.get(id=widget.id).name == "New"

    def test_m2m_is_reassigned(self, db):
        red = Tag.query.create(name="red")
        blue = Tag.query.create(name="blue")
        widget = Widget.query.create(name="Tagged", size="M")
        widget.tags.set([red])

        result = WidgetForm.validate({"name": "Tagged", "size": "M", "tags": [blue.id]})
        assert result
        update_from(widget, result)
        assert set(widget.tags.query) == {blue}


class TestScopingAndInitial:
    def test_with_querysets_narrows_the_choices(self, db):
        keep = Tag.query.create(name="keep")
        hide = Tag.query.create(name="hide")
        scoped = WidgetForm.with_querysets(tags=Tag.query.filter(id=keep.id))

        assert scoped.validate({"name": "A", "size": "S", "tags": [keep.id]})
        # `hide` is no longer one of the field's choices.
        assert not scoped.validate({"name": "A", "size": "S", "tags": [hide.id]})

    def test_initial_from_reads_a_model_instance(self, db):
        red = Tag.query.create(name="red")
        widget = Widget.query.create(name="W", size="L")
        widget.tags.set([red])

        initial = WidgetForm.initial_from(widget)
        assert initial["name"] == "W"
        assert initial["tags"] == [red.id]


class TestDatabaseDefaults:
    """A column the database fills itself isn't user input — `model_field`
    refuses to derive one rather than letting a blank submission fight the
    database default."""

    def test_model_field_rejects_a_database_filled_column(self):
        with pytest.raises(TypeError, match="declare the field explicitly"):
            model_field(DBDefaultsExample.db_uuid)  # UUIDField(generate=True)
        with pytest.raises(TypeError, match="declare the field explicitly"):
            model_field(DBDefaultsExample.created_at)  # DateTimeField(create_now=True)

    def test_explicit_blank_does_not_clobber_db_default(self, db):
        """If a user declares a DB-default column explicitly with `types.*`
        and submits no value, `update_from` must leave the DATABASE_DEFAULT
        sentinel intact so Postgres fills the column itself."""

        class ExplicitForm(ModelForm):
            name = model_field(DBDefaultsExample.name)
            # Deliberately bypass `model_field`'s guard.
            db_uuid = types.UUIDField(required=False)

        result = ExplicitForm.validate({"name": "row"})  # db_uuid omitted
        assert result
        row = create_from(DBDefaultsExample, result)
        # If the empty value had been written, db_uuid would be None and the
        # row would have failed full_clean / a NOT NULL violation.
        assert row.db_uuid is not None
