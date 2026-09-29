"""What a failure report prints for a model instance and for a queryset.

A report prints what a failed test had in hand. It must not run a query to
do it: a query the report ran is one the failing test never did.
"""

from app.examples.models.relationships import Widget
from plain.postgres.test import capture_queries
from plain.postgres.test.lifecycle import PostgresTestLifecycle


def describe(value: object) -> str | None:
    return PostgresTestLifecycle().describe_value(value)


def test_a_model_instance_is_described_by_its_fields():
    widget = Widget.query.create(name="bolt", size="m")

    assert describe(widget) == f"Widget(id={widget.id}, name='bolt', size='m')"
    # Its repr is its class and its id.
    assert repr(widget) == f"<Widget: {widget.id}>"


def test_a_model_instance_that_is_long_has_one_field_to_a_line():
    widget = Widget(name="a considerably longer name for a widget", size="extra large")

    assert describe(widget) == (
        "Widget(\n"
        "    id=None,\n"
        "    name='a considerably longer name for a widget',\n"
        "    size='extra large',\n"
        ")"
    )


def test_a_field_that_was_not_loaded_is_not_fetched():
    Widget.query.create(name="bolt", size="m")
    widget = Widget.query.only("name").get()

    with capture_queries() as queries:
        described = describe(widget)

    assert described == f"Widget(id={widget.id}, name='bolt', size=<not loaded>)"
    assert queries == []


def test_a_queryset_that_has_not_run_is_described_and_is_not_run():
    Widget.query.create(name="bolt", size="m")
    widgets = Widget.query.where(Widget.size.equals("m")).order_by("name")

    with capture_queries() as queries:
        described = describe(widgets)

    assert described == (
        "<QuerySet of Widget, not run: "
        'SELECT "examples_widget"."id", "examples_widget"."name",'
        ' "examples_widget"."size" FROM "examples_widget"'
        ' WHERE "examples_widget"."size" = %s'
        ' ORDER BY "examples_widget"."name" ASC'
        " with ('m',)>"
    )
    assert queries == []
    # Describing it didn't run it, and it can still be narrowed.
    assert widgets._result_cache is None
    assert widgets.where(Widget.name.equals("bolt")).count() == 1


def test_a_queryset_that_has_run_is_described_by_its_rows():
    widget = Widget.query.create(name="bolt", size="m")
    widgets = Widget.query.all()
    assert len(widgets) == 1

    with capture_queries() as queries:
        described = describe(widgets)

    assert described == f"<QuerySet of Widget, 1 row: [<Widget: {widget.id}>]>"
    assert queries == []


def test_a_value_that_is_not_the_databases_is_left_alone():
    assert describe(3) is None
    assert describe("a string") is None
    assert describe([Widget(name="bolt", size="m")]) is None


def test_a_field_kept_encrypted_is_printed_as_withheld():
    from app.examples.models.encrypted import SecretStore

    store = SecretStore(
        name="payments",
        api_key="sk_live_FAKESECRET123",
        config={"token": "FAKESECRET456"},
    )

    described = describe(store)
    assert described == (
        "SecretStore(\n"
        "    id=None,\n"
        "    api_key=<withheld>,\n"
        "    config=<withheld>,\n"
        "    name='payments',\n"
        "    notes='',\n"
        ")"
    )
    assert "FAKESECRET" not in described


def test_a_field_type_says_whether_what_it_holds_is_a_secret():
    from app.examples.models.encrypted import SecretStore

    secret = {
        field.name: field.value_is_secret for field in SecretStore._model_meta.fields
    }
    assert secret == {
        "id": False,
        "name": False,
        "api_key": True,
        "notes": True,
        "config": True,
    }
