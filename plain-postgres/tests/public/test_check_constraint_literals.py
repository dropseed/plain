"""A check constraint's literal is enforced as written.

DDL built from a model runs with no parameters, so a `%` in a literal is a
`%`. It used to be doubled on the way out, which stored `'100%%'` in the
constraint and let the one value the constraint names through.
"""

from app.examples.models.describe import DescribedPerson
from plain.exceptions import ValidationError
from plain.testing import raises


def test_a_percent_in_a_check_literal_is_enforced_as_written():
    DescribedPerson.query.create(name="100%%")

    with raises(ValidationError):
        DescribedPerson.query.create(name="100%")
