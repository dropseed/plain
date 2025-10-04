"""
Test the new RelatedManager API with .query attribute for QuerySet access
"""

from app.examples.models import (  # type: ignore[import-untyped]
    ChildCascade,
    DeleteParent,
)

from plain.models import QuerySet


class TestNewRelatedManagerAPI:
    """Test the new API where managers have .query for QuerySet access"""

    def test_reverse_fk_manager_has_query(self, db):
        """Test that reverse FK managers have .query attribute"""
        parent = DeleteParent.query.create(name="Test Parent")
        child1 = ChildCascade.query.create(parent=parent)
        child2 = ChildCascade.query.create(parent=parent)

        # The manager should have an query attribute
        children_manager = parent.childcascade_set
        assert hasattr(children_manager, "query")

        # The .query attribute should give us a QuerySet
        children_qs = children_manager.query
        assert isinstance(children_qs, QuerySet)

        # QuerySet methods via .query
        assert children_qs.count() == 2
        assert children_qs.filter(id=child1.id).count() == 1
        filtered = children_qs.filter(id=child2.id)
        assert child2 in filtered

    def test_manager_query_attribute(self, db):
        """Test that managers have .query attribute for QuerySet access"""
        parent = DeleteParent.query.create(name="Test Parent")
        ChildCascade.query.create(parent=parent)
        ChildCascade.query.create(parent=parent)

        children_manager = parent.childcascade_set

        # Access QuerySet via .query
        assert children_manager.query.count() == 2
        assert children_manager.query.exists() is True
        assert children_manager.query.first() is not None
        assert children_manager.query.last() is not None

        # all() should return a QuerySet
        all_children = children_manager.query.all()
        assert isinstance(all_children, QuerySet)
        assert all_children.count() == 2

        # filter() should return a QuerySet
        filtered = children_manager.query.filter(id__gt=0)
        assert isinstance(filtered, QuerySet)
        assert filtered.count() == 2

    def test_manager_relationship_methods(self, db):
        """Test that manager-specific methods (add, create, etc.) work"""
        parent = DeleteParent.query.create(name="Test Parent")

        # create() should work on the manager
        child1 = parent.childcascade_set.create()
        assert child1.parent == parent
        assert parent.childcascade_set.query.count() == 1

        # add() should work on the manager
        other_parent = DeleteParent.query.create(name="Other Parent")
        child2 = ChildCascade.query.create(parent=other_parent)
        parent.childcascade_set.add(child2)
        child2.refresh_from_db()
        assert child2.parent == parent
        assert parent.childcascade_set.query.count() == 2

    def test_query_iteration(self, db):
        """Test that iteration works on .query"""
        parent = DeleteParent.query.create(name="Test Parent")
        child1 = ChildCascade.query.create(parent=parent)
        child2 = ChildCascade.query.create(parent=parent)

        # Iterate over .query
        children = list(parent.childcascade_set.query)
        assert len(children) == 2
        assert child1 in children
        assert child2 in children

    def test_chaining_on_query(self, db):
        """Test method chaining on the .query attribute"""
        parent = DeleteParent.query.create(name="Test Parent")
        child1 = ChildCascade.query.create(parent=parent)
        child2 = ChildCascade.query.create(parent=parent)
        child3 = ChildCascade.query.create(parent=parent)

        # Complex chaining via .query
        result = (
            parent.childcascade_set.query.filter(id__gte=child1.id)
            .order_by("id")
            .first()
        )
        assert result.id == child1.id

        # values_list via .query
        ids = list(
            parent.childcascade_set.query.values_list("id", flat=True).order_by("id")
        )
        assert len(ids) == 3
        assert child1.id in ids
        assert child2.id in ids
        assert child3.id in ids

    def test_clear_api_separation(self, db):
        """Test that API clearly separates manager operations from queries"""
        parent = DeleteParent.query.create(name="Test Parent")
        child1 = ChildCascade.query.create(parent=parent)
        child2 = ChildCascade.query.create(parent=parent)

        # Manager operations (relationship management)
        new_child = parent.childcascade_set.create()
        assert new_child.parent == parent

        # QuerySet operations (via .query)
        assert parent.childcascade_set.query.count() == 3
        assert parent.childcascade_set.query.filter(id=child1.id).exists()

        all_children = parent.childcascade_set.query.all()
        assert child1 in all_children
        assert child2 in all_children
        assert new_child in all_children

    def test_multiple_parents(self, db):
        """Test that managers correctly filter by parent"""
        parent1 = DeleteParent.query.create(name="Parent 1")
        parent2 = DeleteParent.query.create(name="Parent 2")

        child1 = ChildCascade.query.create(parent=parent1)
        child2 = ChildCascade.query.create(parent=parent1)
        child3 = ChildCascade.query.create(parent=parent2)

        # Each parent should only see their own children via .query
        assert parent1.childcascade_set.query.count() == 2
        assert parent2.childcascade_set.query.count() == 1

        # Via .query
        assert parent1.childcascade_set.query.count() == 2
        assert child1 in parent1.childcascade_set.query.all()
        assert child2 in parent1.childcascade_set.query.all()
        assert child3 not in parent1.childcascade_set.query.all()

        assert parent2.childcascade_set.query.count() == 1
        assert child3 in parent2.childcascade_set.query.all()
        assert child1 not in parent2.childcascade_set.query.all()
