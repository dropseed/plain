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
