"""Fixture: every template and fragment here is built rather than written."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment, Written
from plain.postgres import Fragment as ShortFragment

# A module-level string is not a template written at the call site: inline it,
# or make the shared thing a Fragment.
TEMPLATE = "SELECT {Widget.*} FROM {Widget}"


def f_string(size):
    return Widget.query.sql(f"SELECT {{Widget.*}} FROM {{Widget}} WHERE s = '{size}'")


def concatenated(order):
    return Widget.query.sql("SELECT {Widget.*} FROM {Widget} ORDER BY " + order)


def from_a_call(builder):
    return Widget.query.sql(builder())


def from_a_variable(template):
    return Widget.query.sql(template)


def keyword_template(template):
    return Widget.query.sql(template=template)


def from_a_module_constant():
    return Widget.query.sql(TEMPLATE)


def from_a_walrus(source):
    return Widget.query.sql(template := source)  # noqa: F841 -- the point of it


def multiline(user_input):
    return Widget.query.sql(
        user_input,
    )


def fragment_from_a_variable(text):
    return Fragment(text)


def fragment_by_keyword(text):
    return Fragment(text=text)


def fragment_from_an_or(text):
    return Fragment(text or "")


def fragment_through_an_alias(text):
    return ShortFragment(text)


def written_directly(template):
    return Written(model=Widget, template=template, values={})
