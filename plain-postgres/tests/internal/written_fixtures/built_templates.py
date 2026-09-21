"""Fixture: every template and fragment here is built at runtime."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment


def f_string(size):
    return Widget.query.sql(
        f"SELECT {{Widget.*}} FROM {{Widget}} WHERE size = '{size}'"
    )


def concatenated(order):
    return Widget.query.sql("SELECT {Widget.*} FROM {Widget} ORDER BY " + order)


def from_a_variable(template):
    return Widget.query.sql(template)


def keyword_template(template):
    return Widget.query.sql(template=template)


def fragment_from_a_variable(text):
    return Fragment(text)


def fragment_by_keyword(text):
    return Fragment(text=text)


def fragment_from_an_or(text):
    return Fragment(text or "")
