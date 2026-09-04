"""A relation holds a "package.Model" string until lazy resolution swaps in
the class. The code that runs before that point (preflight, migration state,
the autodetector) must read the raw reference, and the resolved accessors
must fail loudly rather than be silently skipped by getattr()/hasattr()."""

from __future__ import annotations

import pytest
from plain.postgres import types
from plain.postgres.deletion import CASCADE
from plain.postgres.fields.related import ForeignKeyField, ManyToManyField
from plain.postgres.migrations.autodetector import MigrationAutodetector
from plain.postgres.migrations.state import ModelState, ProjectState
from plain.postgres.migrations.utils import field_references
from plain.postgres.registry import ModelsRegistry


def test_unresolved_model_is_not_swallowed_by_getattr():
    field = types.ForeignKeyField("examples.Missing", on_delete=CASCADE)
    rel = field.remote_field

    assert rel.model_ref == "examples.Missing"
    with pytest.raises(TypeError, match="not been resolved"):
        _ = rel.model
    # getattr()/hasattr() only swallow AttributeError, so a probe can never
    # quietly answer "no model" for a reference that just isn't resolved yet.
    with pytest.raises(TypeError):
        getattr(rel, "model", None)


def test_unresolved_through_is_not_swallowed_by_getattr():
    field = ManyToManyField("examples.Missing", through="examples.MissingThrough")
    rel = field.remote_field

    assert rel.through_ref == "examples.MissingThrough"
    with pytest.raises(TypeError, match="not been resolved"):
        _ = rel.through
    with pytest.raises(TypeError):
        hasattr(rel, "through")


def _tagging_state() -> ProjectState:
    """Post <-M2M through Tagging-> Tag, declared with string references only."""
    state = ProjectState()
    state.add_model(
        ModelState(
            package_label="examples",
            name="Tag",
            fields=[("name", types.TextField())],
        )
    )
    state.add_model(
        ModelState(
            package_label="examples",
            name="Tagging",
            fields=[
                ("post", types.ForeignKeyField("examples.Post", on_delete=CASCADE)),
                ("tag", types.ForeignKeyField("examples.Tag", on_delete=CASCADE)),
            ],
        )
    )
    state.add_model(
        ModelState(
            package_label="examples",
            name="Post",
            fields=[
                ("tags", ManyToManyField("examples.Tag", through="examples.Tagging")),
            ],
        )
    )
    return state


def test_field_references_sees_string_through_model():
    m2m = ManyToManyField("examples.Tag", through="examples.Tagging")

    assert field_references(("examples", "post"), m2m, ("examples", "tagging"))
    assert field_references(("examples", "post"), m2m, ("examples", "tag"))
    assert not field_references(("examples", "post"), m2m, ("examples", "other"))


def test_project_state_relations_index_string_through_model():
    relations = _tagging_state().relations

    assert "tags" in relations[("examples", "tagging")][("examples", "post")]
    assert "tags" in relations[("examples", "tag")][("examples", "post")]


def test_autodetector_maps_string_through_model_users():
    autodetector = MigrationAutodetector(_tagging_state(), _tagging_state())
    autodetector._detect_changes()

    assert autodetector.through_users[("examples", "tagging")] == (
        "examples",
        "post",
        "tags",
    )


def test_preflight_reports_unresolved_relations_instead_of_crashing():
    """Render onto a bare registry so the missing targets stay unresolved:
    the state preflight sees when a model declares a relation to a typo."""
    registry = ModelsRegistry()
    ModelState(
        package_label="examples",
        name="Tag",
        fields=[("name", types.TextField())],
    ).render(registry)
    post = ModelState(
        package_label="examples",
        name="Post",
        fields=[
            ("author", types.ForeignKeyField("examples.Missing", on_delete=CASCADE)),
            (
                "tags",
                ManyToManyField("examples.Tag", through="examples.MissingThrough"),
            ),
            (
                "labels",
                ManyToManyField("examples.MissingTarget", through="examples.Labeling"),
            ),
        ],
    ).render(registry)
    registry.ready = True

    # The model-level entry point `plain preflight` uses must not blow up.
    model_ids = {r.id for r in post.preflight()}
    assert "fields.related_model_not_installed" in model_ids
    assert "fields.m2m_through_model_not_installed" in model_ids

    author = post._model_meta.get_forward_field("author")
    assert isinstance(author, ForeignKeyField)
    assert isinstance(author.remote_field.model_ref, str)
    assert "fields.related_model_not_installed" in {r.id for r in author.preflight()}

    labels, tags = post._model_meta.many_to_many
    assert isinstance(tags.remote_field.through_ref, str)
    assert "fields.m2m_through_model_not_installed" in {
        r.id for r in tags.preflight(from_model=post)
    }
    assert isinstance(labels.remote_field.model_ref, str)
    assert "fields.related_model_not_installed" in {
        r.id for r in labels.preflight(from_model=post)
    }
