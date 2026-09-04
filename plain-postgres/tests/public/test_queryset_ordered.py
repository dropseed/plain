from app.examples.models.mixins import MixinTestModel
from app.examples.models.relationships import Tag


def test_ordered_reflects_model_default_ordering():
    """`QuerySet.ordered` is True when the model declares a default ordering."""
    assert MixinTestModel.model_options.ordering
    assert MixinTestModel.query.all().ordered is True


def test_ordered_reflects_explicit_order_by():
    assert not Tag.model_options.ordering
    assert Tag.query.all().ordered is False
    assert Tag.query.order_by("name").ordered is True
