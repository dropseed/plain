"""`plain postgres models` -- the data model as the registry sees it.

The contract is the facts a reader can't get from a field definition alone:
effective uniqueness (a one-to-one that lives in a unique constraint, a
partial unique that must not be mistaken for one), on-delete rules, the
relations pointing back at a model, and constraint conditions as SQL. None
of it needs a database.
"""

import json

from click.testing import CliRunner
from plain.postgres.cli.models import models as models_cli
from plain.postgres.describe import describe_models


def _run(*args: str) -> str:
    result = CliRunner().invoke(models_cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def _describe(label: str) -> dict:
    output = json.loads(_run(label, "--json"))
    (description,) = output["models"]
    return description


# Effective uniqueness


def test_foreign_key_covered_by_unique_constraint_is_one_to_one():
    profile = _describe("DescribedProfile")
    (person,) = profile["relations"]
    assert person["to"] == "examples.DescribedPerson"
    assert person["on_delete"] == "CASCADE"
    assert person["unique"] is True

    person_model = _describe("DescribedPerson")
    reverse = {r["from"]: r for r in person_model["reverse"]}
    assert reverse["examples.DescribedProfile"]["one_to_one"] is True
    assert reverse["examples.DescribedProfile"]["accessor"] == "profiles"


def test_partial_unique_is_not_promoted_to_uniqueness():
    slot = _describe("DescribedSlot")
    (owner,) = slot["relations"]
    assert owner["unique"] is False

    constraints = {c["name"]: c for c in slot["constraints"]}
    partial = constraints["describedslot_one_active_per_owner"]
    assert partial["kind"] == "unique"
    assert partial["fields"] == ["owner"]
    assert partial["condition"] == '"active"'

    person = _describe("DescribedPerson")
    reverse = {r["from"]: r for r in person["reverse"]}
    assert reverse["examples.DescribedSlot"]["one_to_one"] is False
    assert reverse["examples.DescribedSlot"]["accessor"] is None


def test_single_field_unique_constraint_marks_the_field():
    tag = _describe("Tag")
    fields = {f["name"]: f for f in tag["fields"]}
    assert fields["name"]["unique"] is True
    assert fields["id"]["primary_key"] is True


# Constraints and indexes as SQL


def test_expression_unique_renders_as_sql_and_marks_no_field():
    person = _describe("DescribedPerson")
    fields = {f["name"]: f for f in person["fields"]}
    assert fields["name"]["unique"] is False

    constraints = {c["name"]: c for c in person["constraints"]}
    unique = constraints["describedperson_name_lower_unique"]
    assert unique["fields"] == []
    assert unique["expressions"] == ['(LOWER("name"))']


def test_expression_index_renders_as_sql():
    person = _describe("DescribedPerson")
    (index,) = person["indexes"]
    assert index == {
        "name": "describedperson_name_lower_idx",
        "fields": [],
        "expressions": ['(LOWER("name"))'],
        "condition": None,
    }

    # Written as the DDL writes it, parentheses included.
    assert 'describedperson_name_lower_idx  ((LOWER("name")))' in _run(
        "DescribedPerson"
    )


def test_literals_are_shown_as_postgres_sees_them():
    # A `%` in a literal is a `%`, in the description as in the constraint.
    person = _describe("DescribedPerson")
    constraints = {c["name"]: c for c in person["constraints"]}
    check = constraints["describedperson_name_not_100pct_check"]["check"]
    assert "'100%'" in check
    assert "%%" not in check


def test_check_constraint_and_index_render_as_sql():
    slot = _describe("DescribedSlot")
    constraints = {c["name"]: c for c in slot["constraints"]}
    assert constraints["describedslot_position_check"]["kind"] == "check"
    assert constraints["describedslot_position_check"]["check"] == '"position" >= 0'

    (index,) = slot["indexes"]
    assert index == {
        "name": "describedslot_owner_idx",
        "fields": ["owner"],
        "expressions": [],
        "condition": None,
    }


# Relations


def test_on_delete_and_nullability_per_relation():
    expected = {
        "ChildCascade": ("CASCADE", False),
        "ChildRestrict": ("RESTRICT", False),
        "ChildSetNull": ("SET_NULL", True),
    }
    for name, (on_delete, null) in expected.items():
        (parent,) = _describe(name)["relations"]
        assert (parent["on_delete"], parent["null"]) == (on_delete, null)


def test_many_to_many_names_its_through_model():
    widget = _describe("Widget")
    (tags,) = widget["relations"]
    assert tags["type"] == "ManyToManyField"
    assert tags["to"] == "examples.Tag"
    assert tags["through"] == "examples.WidgetTag"
    assert tags["on_delete"] is None

    tag = _describe("Tag")
    reverse = {r["from"]: r for r in tag["reverse"]}
    assert reverse["examples.Widget"]["type"] == "ManyToManyField"
    assert reverse["examples.Widget"]["accessor"] == "widgets"


# Selection


def test_targets_select_by_model_name_label_or_package():
    by_name = json.loads(_run("Tag", "--json"))["models"]
    by_label = json.loads(_run("examples.Tag", "--json"))["models"]
    assert [m["label"] for m in by_name] == ["examples.Tag"]
    assert by_name == by_label

    by_package = json.loads(_run("examples", "--json"))["models"]
    labels = {m["label"] for m in by_package}
    assert {"examples.Tag", "examples.Widget", "examples.DescribedSlot"} <= labels


def test_default_selection_is_app_models_only():
    default = {m["label"] for m in json.loads(_run("--json"))["models"]}
    everything = {m["label"] for m in json.loads(_run("--json", "--all"))["models"]}
    assert default
    assert all(label.startswith("examples.") for label in default)
    # The test app installs no package that brings models of its own, so
    # --all can only add to the default selection, never take from it.
    assert default <= everything


def test_targets_are_matched_without_regard_to_case_and_kept_in_order():
    output = json.loads(_run("describedslot", "EXAMPLES.DescribedPerson", "--json"))
    assert [m["label"] for m in output["models"]] == [
        "examples.DescribedSlot",
        "examples.DescribedPerson",
    ]


def test_all_with_targets_is_a_usage_error():
    all_with_targets = CliRunner().invoke(models_cli, ["--all", "Tag"])
    assert all_with_targets.exit_code == 2
    assert "--all" in all_with_targets.output


def test_targets_match_by_table_name_too():
    (by_table,) = json.loads(_run("examples_tag", "--json"))["models"]
    assert by_table["label"] == "examples.Tag"


def test_unknown_target_is_an_error():
    result = CliRunner().invoke(models_cli, ["NoSuchModel"])
    assert result.exit_code != 0
    assert "NoSuchModel" in result.output


# Text output


def test_text_output_shows_relations_and_constraints():
    output = _run("DescribedSlot")
    assert "examples.DescribedSlot" in output
    assert "→ examples.DescribedPerson" in output
    assert "CASCADE" in output
    assert "describedslot_one_active_per_owner" in output
    assert 'WHERE "active"' in output
    assert "describedslot_position_check" in output


# Python API


def test_describe_models_matches_the_json_output():
    (description,) = describe_models(("DescribedProfile",))
    assert description.to_dict() == _describe("DescribedProfile")
