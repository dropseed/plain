from __future__ import annotations

from typing import Any

from plain.email import TemplateEmail


def test_template_email_renders_html_subject_and_plain_body() -> None:
    """`TemplateEmail` renders `email/{template}.html` as the HTML body,
    takes the subject from the `subject=` kwarg, and derives the
    plain-text body by stripping tags from the rendered HTML.
    """
    email = TemplateEmail(
        template="welcome",
        subject="Welcome aboard",
        context={"name": "Alice"},
        to=["alice@example.com"],
    )

    assert email.subject == "Welcome aboard"

    html, mimetype = email.alternatives[0]
    assert mimetype == "text/html"
    assert "<h1>Welcome, Alice!</h1>" in html

    # Plain-text body is the tag-stripped HTML.
    assert "Welcome, Alice!" in email.body
    assert "<h1>" not in email.body


def test_template_email_uses_txt_template_for_plain_body() -> None:
    """When `email/{template}.txt` exists, the plain-text body is rendered
    from it through text mode, with `{{ }}` interpolated and no HTML
    parsing or escaping.
    """
    email = TemplateEmail(
        template="digest",
        subject="Your digest",
        context={"user_name": "Alice"},
        to=["alice@example.com"],
    )

    assert "Your digest, Alice!" in email.body
    assert "3 new items." in email.body
    # The plain-text body comes from the .txt file, not the HTML.
    assert "<h1>" not in email.body

    html, _ = email.alternatives[0]
    assert "<h1>Your digest, Alice!</h1>" in html


def test_template_email_render_plain_override() -> None:
    """A subclass can override `render_plain()` to supply a custom
    plain-text body instead of the tag-stripped default.
    """

    class CustomEmail(TemplateEmail):
        def render_plain(self, context: dict[str, Any]) -> str:
            return "Custom plain-text body"

    email = CustomEmail(
        template="welcome",
        subject="Hi",
        context={"name": "Bob"},
        to=["bob@example.com"],
    )

    assert email.body == "Custom plain-text body"
