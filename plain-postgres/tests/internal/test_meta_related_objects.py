"""`Meta.related_objects` -- the reverse-relation index the ORM builds.

Below the contract: users reach reverse relations through the accessor
(`parent.childcascade_set`), which `tests/public/test_related.py` covers. This
pins the index itself, because a regression in it silently empties every
reverse accessor at once.
"""

from app.examples.models.delete import DeleteParent
from plain.postgres.fields.reverse_related import ForeignKeyRel


class TestMetaRelatedObjects:
    def test_meta_related_objects_includes_reverse_fk(self, db):
        """Test that Meta.related_objects includes reverse FK relations.

        Regression test: related_objects was checking obj.field.one_to_many
        instead of obj.one_to_many, which excluded all reverse FK relations.
        """
        # DeleteParent has multiple child models with FKs pointing to it
        related_objs = DeleteParent._model_meta.related_objects

        # Should have reverse FK relations from child models
        assert len(related_objs) > 0, "related_objects should not be empty"

        # Convert to list of field names for easier checking
        related_fields = [obj.field for obj in related_objs]
        related_names = [f.name for f in related_fields]

        # Should include the FK from ChildCascade
        assert "parent" in related_names, (
            "ChildCascade.parent reverse FK should be in related_objects"
        )

        # Find the reverse relation and verify it's a ForeignKeyRel (one_to_many)
        parent_rel = next(obj for obj in related_objs if obj.field.name == "parent")
        assert isinstance(parent_rel, ForeignKeyRel), (
            "Reverse FK should be ForeignKeyRel (one_to_many from parent's perspective)"
        )
