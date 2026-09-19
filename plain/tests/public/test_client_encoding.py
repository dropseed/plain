"""How the test client turns its body arguments into a request.

The client speaks the same vocabulary as the rest of Plain, and the wire
format it picks is part of that contract: a view under test should see the
content type it will see in production.
"""

from __future__ import annotations

from io import BytesIO

from plain.test import RequestFactory, raises


def test_form_data_is_urlencoded_without_files():
    """What a browser sends for a form with no file input."""
    request = RequestFactory().post("/x", form_data={"a": "b", "c": "d"})

    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert dict(request.form_data) == {"a": ["b"], "c": ["d"]}


def test_empty_form_data_is_still_a_form():
    request = RequestFactory().post("/x", form_data={})

    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert request.body == b""


def test_form_data_is_multipart_when_files_are_present():
    request = RequestFactory().post(
        "/x",
        form_data={"title": "Report"},
        files={"upload": BytesIO(b"contents")},
    )

    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert dict(request.form_data) == {"title": ["Report"]}
    assert request.files["upload"].read() == b"contents"


def test_json_data_sets_its_own_content_type():
    request = RequestFactory().post("/x", json_data={"name": "Alice"})

    assert request.headers["Content-Type"] == "application/json"
    assert request.json_data == {"name": "Alice"}


def test_content_type_without_a_body_says_what_to_pass():
    """An empty body under a content type that promises a parseable one would
    fail somewhere inside the view instead of here."""
    with raises(TypeError, match="content_type needs a body"):
        RequestFactory().post("/x", content_type="application/json")


def test_content_type_alongside_form_data_is_rejected():
    with raises(TypeError, match="only applies to a raw body"):
        RequestFactory().post("/x", form_data={"a": "b"}, content_type="text/plain")


def test_raw_body_keeps_the_content_type_it_was_given():
    request = RequestFactory().post("/x", body=b"{}", content_type="application/json")

    assert request.headers["Content-Type"] == "application/json"
    assert request.body == b"{}"
