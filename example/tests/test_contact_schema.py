"""Validates ContactSchema and BoundSchema rendering against the contacts
form template. The full contacts/form.html extends base.html (toolbar,
admin, etc.), which has heavy request requirements — we render a minimal
inline template here that exercises only the BoundSchema interface."""

from __future__ import annotations

import jinja2
from app.contacts.schemas import ContactSchema

from plain.schema import BoundSchema, Invalid

# Inline jinja template exercising the same surface as contacts/form.html:
# html_id, html_name, value(), errors, field.choices, non_field_errors.
FORM_FRAGMENT = jinja2.Template(
    """
{% for err in form.non_field_errors %}<div class="err">{{ err }}</div>{% endfor %}

<input type="text"
       name="{{ form.name.html_name }}"
       id="{{ form.name.html_id }}"
       value="{{ form.name.value() or '' }}">
{% for e in form.name.errors %}<div class="err">{{ e }}</div>{% endfor %}

<input type="email"
       name="{{ form.email.html_name }}"
       id="{{ form.email.html_id }}"
       value="{{ form.email.value() or '' }}">
{% for e in form.email.errors %}<div class="err">{{ e }}</div>{% endfor %}

<select name="{{ form.subject.html_name }}" id="{{ form.subject.html_id }}">
  {% for value, label in form.subject.field.choices %}
  <option value="{{ value }}"{% if form.subject.value() == value %} selected{% endif %}>{{ label }}</option>
  {% endfor %}
</select>
{% for e in form.subject.errors %}<div class="err">{{ e }}</div>{% endfor %}

<textarea name="{{ form.message.html_name }}"
          id="{{ form.message.html_id }}">{{ form.message.value() or '' }}</textarea>
{% for e in form.message.errors %}<div class="err">{{ e }}</div>{% endfor %}

<input type="checkbox"
       name="{{ form.subscribe.html_name }}"
       id="{{ form.subscribe.html_id }}"
       {% if form.subscribe.value() %}checked{% endif %}>

{% if ask_company %}
<input type="text"
       name="{{ form.company.html_name }}"
       id="{{ form.company.html_id }}"
       value="{{ form.company.value() or '' }}">
{% endif %}
"""
)


def _render(form: BoundSchema, *, ask_company: bool = False) -> str:
    return FORM_FRAGMENT.render(form=form, ask_company=ask_company)


def test_contact_schema_validates_valid_input():
    result = ContactSchema.validate(
        {
            "name": "Alice",
            "email": "a@b.co",
            "subject": "general",
            "message": "Hello, this is a long enough message.",
        }
    )
    # Eliminate Invalid → ty narrows result to ContactSchema directly,
    # no `.data` indirection.
    assert not isinstance(result, Invalid)
    assert result.name == "Alice"
    assert result.email == "a@b.co"


def test_contact_schema_blocked_email_domain():
    result = ContactSchema.validate(
        {
            "name": "Alice",
            "email": "alice@blocked.test",
            "subject": "general",
            "message": "Hello, this is a long enough message.",
        }
    )
    assert isinstance(result, Invalid)
    assert "email" in result.errors
    assert "blocked.test" in result.errors["email"][0]


def test_contact_schema_bug_short_message_fails_check():
    """Bug subject with message between 10 (field min_length) and 30
    (check() threshold) — passes field-level, fails cross-field check()."""
    result = ContactSchema.validate(
        {
            "name": "Alice",
            "email": "a@b.co",
            "subject": "bug",
            "message": "thirteen ch.",  # >= 10 chars, < 30
        }
    )
    assert isinstance(result, Invalid)
    assert "__all__" in result.errors
    assert "30 characters" in result.errors["__all__"][0]


def test_bound_schema_unbound_renders_initial():
    form = BoundSchema(schema_class=ContactSchema, initial={"name": "Alice"})
    assert not form.is_bound
    assert form.name.value() == "Alice"
    assert form.email.value() is None
    assert form.email.errors == []
    assert form.subscribe.value() is False  # Field initial


def test_bound_schema_after_invalid_renders_raw_and_errors():
    result = ContactSchema.validate(
        {"name": "X", "email": "bad", "subject": "general", "message": "short"}
    )
    assert isinstance(result, Invalid)
    form = BoundSchema.from_invalid(ContactSchema, result)
    assert form.is_bound
    assert form.name.value() == "X"
    assert "at least 2 characters" in form.name.errors[0]
    assert form.email.value() == "bad"
    assert "valid email" in form.email.errors[0]


def test_template_renders_against_bound_schema():
    """The same template surface used by contacts/form.html renders against
    BoundSchema without modification — duck-typing matches plain.forms.Form.
    """
    form = BoundSchema(schema_class=ContactSchema, initial={"name": "Alice"})
    html = _render(form)
    assert 'id="id_name"' in html
    assert 'value="Alice"' in html
    assert 'id="id_email"' in html
    assert 'id="id_subject"' in html
    assert 'id="id_message"' in html
    assert 'name="subscribe"' in html


def test_template_renders_errors_after_invalid_post():
    result = ContactSchema.validate(
        {"name": "X", "email": "bad", "subject": "general", "message": "short"}
    )
    assert isinstance(result, Invalid)
    form = BoundSchema.from_invalid(ContactSchema, result)
    html = _render(form)
    assert "at least 2 characters" in html
    assert "valid email" in html


def test_template_company_field_only_when_ask_company():
    """The company field exists in the schema but the template only renders
    it when ask_company is True (matching the original ContactForm behavior)."""
    form = BoundSchema(schema_class=ContactSchema)

    html_off = _render(form, ask_company=False)
    assert 'id="id_company"' not in html_off

    html_on = _render(form, ask_company=True)
    assert 'id="id_company"' in html_on


def test_choice_field_selected_after_invalid_repost():
    """When the user submits a valid choice but other fields fail, the
    selected option round-trips back to the user."""
    result = ContactSchema.validate(
        {"name": "X", "email": "bad", "subject": "bug", "message": "short"}
    )
    assert isinstance(result, Invalid)
    form = BoundSchema.from_invalid(ContactSchema, result)
    html = _render(form)
    assert '<option value="bug" selected>' in html


# ---------------------------------------------------------------------------
# File upload via Schema
# ---------------------------------------------------------------------------


def _uploaded(name: str = "report.pdf", content: bytes = b"hello"):
    from plain.internal.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content, "application/pdf")


def test_attachment_upload_schema_validates_file_and_text():
    from app.contacts.schemas import AttachmentUploadSchema

    f = _uploaded()
    result = AttachmentUploadSchema.validate(
        {"description": "Q3 report"}, files={"document": f}
    )
    assert not isinstance(result, Invalid)
    assert result.description == "Q3 report"
    assert result.document.name == "report.pdf"
    assert result.document.size == len(b"hello")


def test_attachment_upload_schema_missing_file_is_required_error():
    from app.contacts.schemas import AttachmentUploadSchema

    result = AttachmentUploadSchema.validate({"description": "Q3 report"}, files={})
    assert isinstance(result, Invalid)
    assert "document" in result.errors


def test_attachment_upload_schema_long_filename_rejected():
    from app.contacts.schemas import AttachmentUploadSchema

    long_name = "x" * 200 + ".pdf"
    result = AttachmentUploadSchema.validate(
        {"description": "ok"}, files={"document": _uploaded(name=long_name)}
    )
    assert isinstance(result, Invalid)
    assert "document" in result.errors


def test_attachment_upload_schema_text_and_file_errors_independently():
    """Both fields can fail independently — validation isn't short-circuited."""
    from app.contacts.schemas import AttachmentUploadSchema

    result = AttachmentUploadSchema.validate({"description": ""}, files={})
    assert isinstance(result, Invalid)
    assert set(result.errors) == {"description", "document"}
