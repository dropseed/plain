from __future__ import annotations

import email
from email.message import Message
from typing import Any

from plain.runtime import settings
from plain.toolbar import ToolbarItem, register_toolbar_item

from .backends.preview import EMAIL_DIR

PREVIEW_BACKEND = "plain.email.backends.preview.EmailBackend"
MAX_MESSAGES = 20


@register_toolbar_item
class EmailToolbarItem(ToolbarItem):
    name = "Email"
    panel_template_name = "toolbar/email.html"

    def is_enabled(self) -> bool:
        return settings.EMAIL_BACKEND == PREVIEW_BACKEND

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["emails"] = _load_recent_messages()
        context["email_file_path"] = str(EMAIL_DIR)
        return context


def _load_recent_messages() -> list[dict[str, Any]]:
    eml_files = sorted(EMAIL_DIR.glob("*.eml"), reverse=True)[:MAX_MESSAGES]

    messages = []
    for eml_file in eml_files:
        with eml_file.open("rb") as f:
            mime = email.message_from_binary_file(f)

        html_body, text_body = _extract_bodies(mime)

        messages.append(
            {
                "id": eml_file.stem,
                "from": mime.get("From", ""),
                "to": mime.get("To", ""),
                "cc": mime.get("Cc", ""),
                "subject": mime.get("Subject", "(no subject)"),
                "date": mime.get("Date", ""),
                "html_body": html_body,
                "text_body": text_body,
                "kind": "html" if html_body else "text",
            }
        )
    return messages


def _extract_bodies(mime: Message) -> tuple[str | None, str | None]:
    html_body: str | None = None
    text_body: str | None = None

    for part in mime.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        if content_type == "text/html" and html_body is None:
            html_body = _decode_part(part)
        elif content_type == "text/plain" and text_body is None:
            text_body = _decode_part(part)

    return html_body, text_body


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")
