from app.examples.models.mixins import MixinTestModel


def test_mixin_fields_inherited(db):
    """Test that fields from mixins are properly inherited and processed."""
    # Verify mixin fields are present
    field_names = [f.name for f in MixinTestModel._model_meta.fields]
    assert "created_at" in field_names, "created_at from mixin should be present"
    assert "updated_at" in field_names, "updated_at from mixin should be present"
    assert "name" in field_names, "name from model should be present"

    # Verify ordering from Options works
    assert MixinTestModel.model_options.ordering == ["-created_at"]

    # Verify we can create instances
    instance = MixinTestModel.query.create(name="test")
    assert instance.created_at is not None
    assert instance.updated_at is not None
    assert instance.name == "test"
