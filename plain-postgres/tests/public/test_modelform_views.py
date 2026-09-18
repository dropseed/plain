"""Public contract — a ModelForm driven over HTTP.

`test_modelform.py` covers `validate()` / `create_from()` / `update_from()`
directly. This is the other half: the same API through real requests, so the
round-trip a user actually takes — render the form, submit it, get it back with
errors, fix it, land the write — is covered end to end.
"""

from __future__ import annotations

from app.examples.models.relationships import Widget
from plain.test import Client


class TestCreate:
    def test_get_renders_a_blank_form(self, db):
        response = Client().get("/widgets/new")

        assert response.status_code == 200
        body = response.content.decode()
        assert 'name="name"' in body
        assert 'name="size"' in body

    def test_post_creates_the_row_and_redirects(self, db):
        response = Client().post("/widgets/new", data={"name": "Cog", "size": "S"})

        widget = Widget.query.get(name="Cog")
        assert response.status_code == 302
        assert response.headers["Location"] == f"/widgets/{widget.id}/edit"
        assert widget.size == "S"

    def test_invalid_post_re_renders_with_errors_and_writes_nothing(self, db):
        response = Client().post("/widgets/new", data={"name": "Cog"})  # no size

        assert response.status_code == 200
        assert "This field is required." in response.content.decode()
        assert not Widget.query.filter(name="Cog").exists()

    def test_invalid_post_shows_what_was_submitted(self, db):
        response = Client().post("/widgets/new", data={"name": "Cog"})

        assert 'value="Cog"' in response.content.decode()

    def test_duplicate_is_re_rendered_not_a_500(self, db):
        """The constraint pre-check means a unique violation comes back as a
        form error rather than escaping the view as a ValidationError."""
        Widget.query.create(name="Cog", size="S")

        response = Client().post("/widgets/new", data={"name": "Cog", "size": "S"})

        assert response.status_code == 200
        assert "already exists" in response.content.decode()
        assert Widget.query.filter(name="Cog").count() == 1


class TestUpdate:
    def test_get_pre_fills_from_the_row(self, db):
        widget = Widget.query.create(name="Cog", size="S")

        body = Client().get(f"/widgets/{widget.id}/edit").content.decode()

        assert 'value="Cog"' in body
        assert 'value="S"' in body

    def test_post_writes_onto_the_row(self, db):
        widget = Widget.query.create(name="Cog", size="S")

        response = Client().post(
            f"/widgets/{widget.id}/edit", data={"name": "Sprocket", "size": "L"}
        )

        assert response.status_code == 302
        widget = Widget.query.get(id=widget.id)
        assert (widget.name, widget.size) == ("Sprocket", "L")

    def test_resubmitting_unchanged_values_is_allowed(self, db):
        """The row must not collide with itself in the uniqueness pre-check."""
        widget = Widget.query.create(name="Cog", size="S")

        response = Client().post(
            f"/widgets/{widget.id}/edit", data={"name": "Cog", "size": "S"}
        )

        assert response.status_code == 302

    def test_colliding_with_another_row_is_re_rendered(self, db):
        widget = Widget.query.create(name="Cog", size="S")
        Widget.query.create(name="Sprocket", size="L")

        response = Client().post(
            f"/widgets/{widget.id}/edit", data={"name": "Sprocket", "size": "L"}
        )

        assert response.status_code == 200
        assert "already exists" in response.content.decode()
        assert Widget.query.get(id=widget.id).name == "Cog"

    def test_invalid_post_leaves_the_row_alone(self, db):
        widget = Widget.query.create(name="Cog", size="S")

        response = Client().post(f"/widgets/{widget.id}/edit", data={"name": ""})

        assert response.status_code == 200
        assert Widget.query.get(id=widget.id).name == "Cog"

    def test_a_missing_row_is_404(self, db):
        assert Client().get("/widgets/999999/edit").status_code == 404


class TestDelete:
    def test_get_renders_the_confirmation(self, db):
        widget = Widget.query.create(name="Cog", size="S")

        response = Client().get(f"/widgets/{widget.id}/delete")

        assert response.status_code == 200
        assert "Delete Cog?" in response.content.decode()

    def test_post_deletes_the_row(self, db):
        widget = Widget.query.create(name="Cog", size="S")

        response = Client().post(f"/widgets/{widget.id}/delete")

        assert response.status_code == 302
        assert not Widget.query.filter(id=widget.id).exists()
