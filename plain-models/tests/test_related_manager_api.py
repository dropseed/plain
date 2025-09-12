"""
Test the new RelatedManager API with .objects attribute for QuerySet access
"""

from app.examples.models import (
    ChildCascade,
    DeleteParent,
)

from plain.models import QuerySet


class TestNewRelatedManagerAPI:
    """Test the new API where managers have .objects for QuerySet access"""

    def test_reverse_fk_manager_has_objects(self, db):
        """Test that reverse FK managers have .objects attribute"""
        parent = DeleteParent.objects.create(name="Test Parent")
        child1 = ChildCascade.objects.create(parent=parent)
        child2 = ChildCascade.objects.create(parent=parent)

        # The manager should have an objects attribute
        children_manager = parent.childcascade_set
        assert hasattr(children_manager, "objects")

        # The .objects attribute should give us a QuerySet
        children_qs = children_manager.objects
        assert isinstance(children_qs, QuerySet)

        # QuerySet methods via .objects
        assert children_qs.count() == 2
        assert children_qs.filter(id=child1.id).count() == 1
        filtered = children_qs.filter(id=child2.id)
        assert child2 in filtered

    def test_manager_objects_attribute(self, db):
        """Test that managers have .objects attribute for QuerySet access"""
        parent = DeleteParent.objects.create(name="Test Parent")
        ChildCascade.objects.create(parent=parent)
        ChildCascade.objects.create(parent=parent)

        children_manager = parent.childcascade_set

        # Access QuerySet via .objects
        assert children_manager.objects.count() == 2
        assert children_manager.objects.exists() is True
        assert children_manager.objects.first() is not None
        assert children_manager.objects.last() is not None

        # all() should return a QuerySet
        all_children = children_manager.objects.all()
        assert isinstance(all_children, QuerySet)
        assert all_children.count() == 2

        # filter() should return a QuerySet
        filtered = children_manager.objects.filter(id__gt=0)
        assert isinstance(filtered, QuerySet)
        assert filtered.count() == 2

    def test_manager_relationship_methods(self, db):
        """Test that manager-specific methods (add, create, etc.) work"""
        parent = DeleteParent.objects.create(name="Test Parent")

        # create() should work on the manager
        child1 = parent.childcascade_set.create()
        assert child1.parent == parent
        assert parent.childcascade_set.objects.count() == 1

        # add() should work on the manager
        other_parent = DeleteParent.objects.create(name="Other Parent")
        child2 = ChildCascade.objects.create(parent=other_parent)
        parent.childcascade_set.add(child2)
        child2.refresh_from_db()
        assert child2.parent == parent
        assert parent.childcascade_set.objects.count() == 2

    def test_objects_iteration(self, db):
        """Test that iteration works on .objects"""
        parent = DeleteParent.objects.create(name="Test Parent")
        child1 = ChildCascade.objects.create(parent=parent)
        child2 = ChildCascade.objects.create(parent=parent)

        # Iterate over .objects
        children = list(parent.childcascade_set.objects)
        assert len(children) == 2
        assert child1 in children
        assert child2 in children

    def test_chaining_on_objects(self, db):
        """Test method chaining on the .objects attribute"""
        parent = DeleteParent.objects.create(name="Test Parent")
        child1 = ChildCascade.objects.create(parent=parent)
        child2 = ChildCascade.objects.create(parent=parent)
        child3 = ChildCascade.objects.create(parent=parent)

        # Complex chaining via .objects
        result = (
            parent.childcascade_set.objects.filter(id__gte=child1.id)
            .order_by("id")
            .first()
        )
        assert result.id == child1.id

        # values_list via .objects
        ids = list(
            parent.childcascade_set.objects.values_list("id", flat=True).order_by("id")
        )
        assert len(ids) == 3
        assert child1.id in ids
        assert child2.id in ids
        assert child3.id in ids

    def test_clear_api_separation(self, db):
        """Test that API clearly separates manager operations from queries"""
        parent = DeleteParent.objects.create(name="Test Parent")
        child1 = ChildCascade.objects.create(parent=parent)
        child2 = ChildCascade.objects.create(parent=parent)

        # Manager operations (relationship management)
        new_child = parent.childcascade_set.create()
        assert new_child.parent == parent

        # QuerySet operations (via .objects)
        assert parent.childcascade_set.objects.count() == 3
        assert parent.childcascade_set.objects.filter(id=child1.id).exists()

        all_children = parent.childcascade_set.objects.all()
        assert child1 in all_children
        assert child2 in all_children
        assert new_child in all_children

    def test_multiple_parents(self, db):
        """Test that managers correctly filter by parent"""
        parent1 = DeleteParent.objects.create(name="Parent 1")
        parent2 = DeleteParent.objects.create(name="Parent 2")

        child1 = ChildCascade.objects.create(parent=parent1)
        child2 = ChildCascade.objects.create(parent=parent1)
        child3 = ChildCascade.objects.create(parent=parent2)

        # Each parent should only see their own children via .objects
        assert parent1.childcascade_set.objects.count() == 2
        assert parent2.childcascade_set.objects.count() == 1

        # Via .objects
        assert parent1.childcascade_set.objects.count() == 2
        assert child1 in parent1.childcascade_set.objects.all()
        assert child2 in parent1.childcascade_set.objects.all()
        assert child3 not in parent1.childcascade_set.objects.all()

        assert parent2.childcascade_set.objects.count() == 1
        assert child3 in parent2.childcascade_set.objects.all()
        assert child1 not in parent2.childcascade_set.objects.all()
