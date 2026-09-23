"""Encrypted fields: what they store, and what they refuse to match on.

The static half of the refusal -- every condition the type checker must
reject, and the `is_null`/`equals(None)`/`equals("")` surface that must
survive it -- lives in `tests/typing/conditions_encrypted.py`. The
encrypt/decrypt primitives are in `tests/internal/test_encrypted_internals.py`.
"""

import pytest
from app.examples.models.encrypted import SecretStore
from plain.postgres import F, Q, types
from plain.postgres.exceptions import FieldError


class TestEncryptedTextField:
    def test_create_and_read(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-abc123")
        obj.refresh_from_db()
        assert obj.api_key == "sk-abc123"

    def test_update(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-old")
        obj.api_key = "sk-new"
        obj.update()
        obj.refresh_from_db()
        assert obj.api_key == "sk-new"

    def test_null_not_encrypted(self, db):
        """NULL values should stay as NULL, not get encrypted."""
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None

    def test_queryset_values(self, db):
        """Raw DB values should be encrypted ciphertext."""
        SecretStore.query.create(name="test", api_key="sk-secret")
        raw = SecretStore.query.values_list("api_key", flat=True).first()
        # The raw value from values_list goes through from_db_value,
        # so it should be decrypted
        assert raw == "sk-secret"

    def test_long_text(self, db):
        long_text = "x" * 10000
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes=long_text)
        obj.refresh_from_db()
        assert obj.notes == long_text

    def test_empty_string(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes="")
        obj.refresh_from_db()
        assert obj.notes == ""


class TestEncryptedJSONField:
    def test_dict(self, db):
        data = {"token": "abc", "scopes": ["read", "write"]}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_list(self, db):
        data = [1, 2, "three"]
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_nested(self, db):
        data = {"oauth": {"access_token": "gho_xxx", "refresh_token": "ghr_yyy"}}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_null(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None


class TestLookupBlocking:
    def test_isnull_lookup_works(self, db):
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config__isnull=True).count() == 1

    def test_exact_lookup_allowed(self):
        """Exact is allowed so filter(field=None) works (ORM rewrites to isnull)."""
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("exact") is not None

    def test_filter_none_works(self, db):
        """filter(field=None) must work — ORM rewrites exact+None to isnull."""
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config=None).count() == 1

    def test_contains_lookup_blocked(self):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("contains") is None

    def test_transform_blocked(self):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_transform("lower") is None  # ty: ignore[unresolved-attribute]

    def test_unsupported_lookup_raises_field_error(self):
        """An unsupported lookup on an encrypted field must fail as a normal
        FieldError at query-build time — not leak into transform resolution
        (which once raised a bare TypeError via class-level get_lookups)."""
        with pytest.raises(FieldError):
            SecretStore.query.filter(api_key__contains="x")
        with pytest.raises(FieldError):
            SecretStore.query.filter(config__has_key="token")


class TestTypedQueryMethodsBlocked:
    """Encrypted fields must not expose typed-query comparison methods.

    The class-level overrides accept `Never`, so type checkers reject any
    call site (pinned in `tests/typing/conditions_encrypted.py`). The runtime
    also raises TypeError as a safety net for callers that bypass type
    checking (e.g. dynamic code) -- that half is what these assert.
    """

    def test_equals_raises(self):
        with pytest.raises(TypeError, match=r"api_key.*does not support \.equals\("):
            SecretStore.api_key.equals("anything")  # ty: ignore[no-matching-overload]

    def test_not_equal_raises(self):
        with pytest.raises(TypeError, match=r"does not support \.not_equal\("):
            SecretStore.api_key.not_equal("x")  # ty: ignore[no-matching-overload]

    @pytest.mark.parametrize("method", ["gt", "gte", "lt", "lte"])
    def test_ordering_comparison_raises(self, method):
        with pytest.raises(TypeError, match=rf"does not support \.{method}\("):
            getattr(SecretStore.api_key, method)("x")

    def test_is_in_raises(self):
        with pytest.raises(TypeError, match=r"does not support \.is_in\("):
            SecretStore.api_key.is_in(["x", "y"])  # ty: ignore[invalid-argument-type]

    @pytest.mark.parametrize(
        "method", ["contains", "icontains", "startswith", "endswith"]
    )
    def test_text_pattern_condition_raises(self, method):
        """EncryptedTextField inherits TextField's pattern conditions and
        blocks them — matching ciphertext by substring is meaningless."""
        with pytest.raises(TypeError, match=rf"does not support \.{method}\("):
            getattr(SecretStore.api_key, method)("x")

    @pytest.mark.parametrize(
        "method", ["equals", "not_equal", "gt", "gte", "lt", "lte", "is_in"]
    )
    def test_json_field_comparison_raises(self, method):
        """EncryptedJSONField carries the same block."""
        with pytest.raises(TypeError, match=rf"does not support \.{method}\("):
            getattr(SecretStore.config, method)("x")

    def test_is_null_returns_correct_lookup(self):
        """is_null is the one comparison that makes sense on ciphertext."""
        q = SecretStore.api_key.is_null()
        assert isinstance(q, Q)
        assert q.children == [("api_key__isnull", True)]

        q_false = SecretStore.api_key.is_null(False)
        assert q_false.children == [("api_key__isnull", False)]


class TestKwargFilterBlocked:
    """Block the legacy kwarg/Q path the same way the typed methods are
    blocked: `filter(api_key='x')` on an encrypted field would silently
    return zero rows because ciphertext is non-deterministic.
    `filter(api_key=None)` is preserved so it still rewrites to IS NULL.
    """

    def test_filter_non_none_raises(self, db):
        with pytest.raises(TypeError, match=r"api_key.*cannot be matched against"):
            SecretStore.query.filter(api_key="sk-test").count()

    def test_exclude_non_none_raises(self, db):
        with pytest.raises(TypeError, match=r"api_key.*cannot be matched against"):
            SecretStore.query.exclude(api_key="sk-test").count()

    def test_filter_none_still_rewrites_to_isnull(self, db):
        """filter(field=None) must continue to work — ORM rewrites to isnull."""
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config=None).count() == 1

    def test_get_or_create_on_an_encrypted_lookup_raises(self, db):
        """A deliberate break. This used to "work": ciphertext never matched,
        so every call created another row. Raising is the point of the block,
        and the message has to say where the value belongs instead."""
        with pytest.raises(TypeError, match=r"move 'api_key' into defaults="):
            SecretStore.query.get_or_create(name="test", api_key="sk-test", config=None)

    def test_get_or_create_with_the_encrypted_value_in_defaults_works(self, db):
        """The spelling the message points at."""
        obj, created = SecretStore.query.get_or_create(
            name="test", defaults={"api_key": "sk-test", "config": None}
        )
        assert created
        assert obj.api_key == "sk-test"

        again, created_again = SecretStore.query.get_or_create(
            name="test", defaults={"api_key": "other", "config": None}
        )
        assert not created_again
        assert again.id == obj.id

    def test_filter_against_an_expression_raises(self, db):
        """An F() right-hand side is a value comparison too — the column is
        still ciphertext, so it can never match."""
        with pytest.raises(TypeError, match=r"api_key.*cannot be matched against"):
            SecretStore.query.filter(api_key=F("name")).count()


class TestEncryptedJSONFieldDefault:
    """`EncryptedJSONField` has no *persistent* default — ciphertext is
    non-deterministic, so no literal column DEFAULT can be expressed. It still
    accepts `default=None` on a nullable field, the same None-only affordance
    the ColumnField-direct fields (UUIDField, DateTimeField, ForeignKeyField)
    use to mark a field optional in the typed constructor."""

    def test_default_none_is_accepted_on_a_nullable_field(self):
        field = types.EncryptedJSONField(required=False, allow_null=True, default=None)

        assert field.get_default() is None
        # Nothing is stored, so no DB DEFAULT and no migration churn.
        assert not field.has_persistent_literal_default()
        assert not field.has_persistent_column_default()

    def test_default_none_makes_the_field_omittable(self, db):
        """The point of the `default=None`: `config` is declared with it on
        SecretStore, so it can be left out of the constructor entirely and the
        row still saves."""
        obj = SecretStore(name="test", api_key="sk-omitted")
        assert obj.config is None

        obj.create()
        assert SecretStore.query.get(name="test").config is None

    def test_default_none_requires_allow_null(self):
        # The stub refuses this too -- see tests/typing/field_constructors.py.
        with pytest.raises(TypeError, match="requires allow_null=True"):
            types.EncryptedJSONField(required=False, default=None)  # ty: ignore[no-matching-overload]

    @pytest.mark.parametrize("value", [{}, {"a": 1}, [], "", 0])
    def test_literal_default_is_still_rejected(self, value):
        """Any non-None default would need ciphertext, which is
        non-deterministic — there is no literal to put in the column."""
        with pytest.raises(TypeError, match="does not accept a persistent default"):
            types.EncryptedJSONField(required=False, allow_null=True, default=value)


class TestDeterministicValuesStillMatch:
    """The empty string is stored as plaintext `''` (that is what makes
    `default=""` expressible as a column DEFAULT), so equality against it is
    meaningful and must keep working -- on both the kwarg and the typed path,
    which must agree with each other."""

    def test_filter_on_empty_string_works(self, db):
        SecretStore.query.create(name="blank", api_key="k", notes="", config=None)
        SecretStore.query.create(name="filled", api_key="k", notes="x", config=None)

        assert SecretStore.query.filter(notes="").count() == 1
        assert SecretStore.query.exclude(notes="").count() == 1

    def test_get_or_create_on_empty_string_works(self, db):
        obj, created = SecretStore.query.get_or_create(
            notes="", defaults={"name": "blank", "api_key": "k", "config": None}
        )
        assert created
        again, created_again = SecretStore.query.get_or_create(
            notes="", defaults={"name": "other", "api_key": "k", "config": None}
        )
        assert not created_again
        assert again.id == obj.id

    def test_typed_equals_matches_the_kwarg_path(self):
        """`equals(None)` and `filter(field=None)` can't disagree, and the
        error message advertises `=None`, so the typed path has to allow it."""
        assert SecretStore.api_key.equals(None).children == [("api_key", None)]
        assert SecretStore.notes.equals("").children == [("notes", "")]
        assert SecretStore.notes.not_equal("").children == [("notes", "")]

    def test_where_filters_on_the_empty_string(self, db):
        SecretStore.query.create(name="blank", api_key="k", notes="", config=None)
        SecretStore.query.create(name="filled", api_key="k", notes="x", config=None)

        rows = list(SecretStore.query.where(SecretStore.notes.equals("")))
        assert [r.name for r in rows] == ["blank"]

    def test_a_real_value_is_still_blocked(self, db):
        with pytest.raises(TypeError, match=r"does not support \.equals\("):
            SecretStore.notes.equals("something")  # ty: ignore[no-matching-overload]
        with pytest.raises(TypeError, match=r"cannot be matched against"):
            SecretStore.query.filter(notes="something").count()

    def test_json_field_allows_none_but_not_empty_string(self):
        """Only text stores "" as plaintext; an empty string on a JSON column
        would still be encrypted, so it stays blocked."""
        assert SecretStore.config.equals(None).children == [("config", None)]
        with pytest.raises(TypeError, match=r"does not support \.equals\("):
            SecretStore.config.equals("")  # ty: ignore[no-matching-overload]
