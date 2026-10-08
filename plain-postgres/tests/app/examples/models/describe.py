"""Models for `plain postgres models` (`plain.postgres.describe`).

They stage the facts a reader can't get from a field definition alone: a
one-to-one that lives in a unique constraint, a partial unique that must not
be mistaken for one, a check constraint, and a declared reverse accessor.
"""

from typing import ClassVar

from plain.postgres import Field, types
from plain.postgres.functions import Lower
from plain.postgres.query_utils import Q

from plain import postgres


@postgres.register_model
class DescribedPerson(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    profiles: ClassVar[types.ReverseForeignKey[DescribedProfile]] = (
        types.ReverseForeignKey(to="DescribedProfile", field="person")
    )

    model_options = postgres.Options(
        constraints=[
            # Unique over an expression: not a field, so `name` stays
            # unmarked and the constraint carries the SQL.
            postgres.UniqueConstraint(
                Lower("name"), name="describedperson_name_lower_unique"
            ),
            # A literal with a `%` in it: shown as Postgres sees it.
            postgres.CheckConstraint(
                check=~Q(name="100%"), name="describedperson_name_not_100pct_check"
            ),
            # The same, in a partial unique's condition: lives as an index.
            postgres.UniqueConstraint(
                fields=["name"],
                condition=~Q(name__endswith="%"),
                name="describedperson_name_unique_unless_pct",
            ),
        ],
        indexes=[
            postgres.Index(Lower("name"), name="describedperson_name_lower_idx"),
        ],
    )


@postgres.register_model
class DescribedProfile(postgres.Model):
    """One per person, by constraint rather than by field."""

    person: Field[DescribedPerson] = types.ForeignKeyField(
        DescribedPerson, on_delete=postgres.CASCADE
    )
    bio: Field[str] = types.TextField(required=False, default="")

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["person"], name="describedprofile_person_unique"
            ),
        ]
    )


@postgres.register_model
class DescribedSlot(postgres.Model):
    """At most one active slot per owner: a partial unique, not a one-to-one."""

    owner: Field[DescribedPerson] = types.ForeignKeyField(
        DescribedPerson, on_delete=postgres.CASCADE
    )
    active: Field[bool] = types.BooleanField(default=False)
    position: Field[int] = types.IntegerField(default=0)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["owner"],
                condition=Q(active=True),
                name="describedslot_one_active_per_owner",
            ),
            postgres.CheckConstraint(
                check=Q(position__gte=0), name="describedslot_position_check"
            ),
        ],
        indexes=[
            postgres.Index(fields=["owner"], name="describedslot_owner_idx"),
        ],
    )
