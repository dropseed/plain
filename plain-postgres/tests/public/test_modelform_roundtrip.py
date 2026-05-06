"""System-style ModelForm round-trip tests.

These POST form data through a view and verify the full stack works:
ModelForm build (via modelfield_to_formfield) → form binding on POST →
cleaned_data → model save. Covers a representative spread of postgres
field types so regressions in form-field selection or coercion surface
immediately.
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal

from app.examples.models.defaults import DBDefaultsExample
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.encrypted import SecretStore
from app.examples.models.forms import FormsExample

from plain.test import Client


def _valid_post_data() -> dict[str, str]:
    return {
        "name": "Widget A",
        "status": "published",
        "note": "",  # allow_null=True + required=False → empty posts as None
        "count": "42",
        "ratio": "1.5",
        "amount": "99.99",
        "is_active": "on",
        "event_date": "2026-04-15",
        "event_time": "14:30:00",
        "event_datetime": "2026-04-15 14:30:00",
        "duration": "01:30:00",
        "external_id": "123e4567-e89b-12d3-a456-426614174000",
    }


class TestFormsExampleCreate:
    def test_create_roundtrip_all_field_types(self, db):
        client = Client()
        response = client.post("/examples/forms/create/", data=_valid_post_data())

        assert response.status_code == 302, response.content
        assert response.headers["Location"] == "/ok/"

        obj = FormsExample.query.get()
        assert obj.name == "Widget A"
        assert obj.status == "published"
        assert obj.note is None
        assert obj.count == 42
        assert obj.ratio == 1.5
        assert obj.amount == Decimal("99.99")
        assert obj.is_active is True
        assert obj.event_date == datetime.date(2026, 4, 15)
        assert obj.event_time == datetime.time(14, 30, 0)
        assert obj.event_datetime.year == 2026
        assert obj.event_datetime.month == 4
        assert obj.event_datetime.day == 15
        assert obj.event_datetime.hour == 14
        assert obj.event_datetime.minute == 30
        assert obj.duration == datetime.timedelta(hours=1, minutes=30)
        assert obj.external_id == uuid.UUID("123e4567-e89b-12d3-a456-426614174000")

    def test_boolean_false_when_checkbox_unchecked(self, db):
        client = Client()
        data = _valid_post_data()
        del data["is_active"]  # unchecked checkboxes aren't posted
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 302, response.content
        assert FormsExample.query.get().is_active is False

    def test_invalid_integer_returns_400_with_field_error(self, db):
        client = Client()
        data = _valid_post_data()
        data["count"] = "not-an-int"
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "count" in errors

    def test_invalid_choice_returns_400(self, db):
        client = Client()
        data = _valid_post_data()
        data["status"] = "archived"  # not in the declared choices
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "status" in errors

    def test_invalid_uuid_returns_400(self, db):
        client = Client()
        data = _valid_post_data()
        data["external_id"] = "not-a-uuid"
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "external_id" in errors

    def test_invalid_date_returns_400(self, db):
        client = Client()
        data = _valid_post_data()
        data["event_date"] = "not-a-date"
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "event_date" in errors

    def test_blank_required_field_returns_400_with_error(self, db):
        """Required field sent as empty string → form_invalid path with errors."""
        client = Client()
        data = _valid_post_data()
        data["name"] = ""
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "name" in errors

    def test_omitted_required_field_returns_400(self, db):
        """Required field entirely absent from POST data → framework-level 400."""
        client = Client()
        data = _valid_post_data()
        del data["name"]
        response = client.post("/examples/forms/create/", data=data)

        assert response.status_code == 400


class TestFormsExampleUpdate:
    def _create_existing(self) -> FormsExample:
        return FormsExample.query.create(
            name="Before",
            status="draft",
            count=1,
            ratio=0.5,
            amount=Decimal("1.00"),
            event_date=datetime.date(2020, 1, 1),
            event_time=datetime.time(0, 0, 0),
            event_datetime=datetime.datetime(2020, 1, 1, 0, 0, 0, tzinfo=datetime.UTC),
            duration=datetime.timedelta(minutes=1),
            external_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        )

    def test_update_roundtrip_persists_changed_fields(self, db):
        existing = self._create_existing()
        client = Client()
        data = _valid_post_data()
        data["name"] = "After"
        data["count"] = "100"

        response = client.post(f"/examples/forms/{existing.id}/update/", data=data)

        assert response.status_code == 302, response.content

        existing.refresh_from_db()
        assert existing.name == "After"
        assert existing.count == 100
        assert existing.status == "published"
        assert existing.amount == Decimal("99.99")

    def test_update_with_invalid_data_does_not_save(self, db):
        existing = self._create_existing()
        client = Client()
        data = _valid_post_data()
        data["count"] = "not-an-int"

        response = client.post(f"/examples/forms/{existing.id}/update/", data=data)

        assert response.status_code == 400
        existing.refresh_from_db()
        assert existing.name == "Before"
        assert existing.count == 1


class TestForeignKeyRoundTrip:
    """Exercises the explicit ForeignKeyField → ModelChoiceField handler."""

    def test_create_with_valid_fk(self, db):
        parent = DeleteParent.query.create(name="parent-1")
        client = Client()
        response = client.post(
            "/examples/child-cascade/create/", data={"parent": str(parent.id)}
        )

        assert response.status_code == 302, response.content
        child = ChildCascade.query.get()
        assert child.parent_id == parent.id  # ty: ignore[unresolved-attribute]

    def test_create_with_nonexistent_fk_returns_400(self, db):
        client = Client()
        response = client.post(
            "/examples/child-cascade/create/", data={"parent": "999999"}
        )

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "parent" in errors

    def test_create_with_blank_required_fk_returns_400(self, db):
        client = Client()
        response = client.post("/examples/child-cascade/create/", data={"parent": ""})

        assert response.status_code == 400
        errors = json.loads(response.content)
        assert "parent" in errors


class TestDBExpressionDefaultsRoundTrip:
    """DB-expression defaults (create_now=True, generate=True) must let the
    user omit the value so Postgres fills it on INSERT. modelfield_to_formfield
    sets required=False for fields where db_returning is True."""

    def test_blank_db_default_fields_are_filled_by_database(self, db):
        client = Client()
        response = client.post(
            "/examples/db-defaults/create/",
            data={"name": "sample", "db_uuid": "", "created_at": ""},
        )

        assert response.status_code == 302, response.content
        obj = DBDefaultsExample.query.get()
        assert obj.name == "sample"
        assert isinstance(obj.db_uuid, uuid.UUID)
        assert isinstance(obj.created_at, datetime.datetime)

    def test_user_supplied_value_overrides_db_default(self, db):
        supplied = "11111111-1111-1111-1111-111111111111"
        client = Client()
        response = client.post(
            "/examples/db-defaults/create/",
            data={
                "name": "sample",
                "db_uuid": supplied,
                "created_at": "2026-01-02 03:04:05",
            },
        )

        assert response.status_code == 302, response.content
        obj = DBDefaultsExample.query.get()
        assert obj.db_uuid == uuid.UUID(supplied)
        assert obj.created_at.year == 2026
        assert obj.created_at.month == 1
        assert obj.created_at.day == 2


class TestEncryptedFieldsRoundTrip:
    """EncryptedTextField and EncryptedJSONField round-trip through the
    ModelForm → POST → save path with transparent encrypt/decrypt."""

    def test_create_roundtrip_with_encrypted_text(self, db):
        client = Client()
        response = client.post(
            "/examples/secret-store/create/",
            data={
                "name": "prod-key",
                "api_key": "sk-live-abc123",
                "notes": "rotate monthly",
                "config": json.dumps({"region": "us-east-1"}),
            },
        )

        assert response.status_code == 302, response.content
        obj = SecretStore.query.get()
        assert obj.name == "prod-key"
        assert obj.api_key == "sk-live-abc123"
        assert obj.notes == "rotate monthly"
        assert obj.config == {"region": "us-east-1"}

    def test_blank_optional_encrypted_text_accepted(self, db):
        client = Client()
        response = client.post(
            "/examples/secret-store/create/",
            data={
                "name": "minimal",
                "api_key": "sk-test",
                "notes": "",
                "config": "",
            },
        )

        assert response.status_code == 302, response.content
        obj = SecretStore.query.get()
        assert obj.name == "minimal"
        assert obj.api_key == "sk-test"
        assert obj.notes == ""
        assert obj.config is None
