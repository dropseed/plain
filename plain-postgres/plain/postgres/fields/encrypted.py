from __future__ import annotations

import base64
import json
from functools import cache
from typing import TYPE_CHECKING, Any, Never

try:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    Fernet = None  # ty: ignore[invalid-assignment]
    InvalidToken = None  # ty: ignore[invalid-assignment]
    MultiFernet = None  # ty: ignore[invalid-assignment]
    hashes = None  # ty: ignore[invalid-assignment]
    PBKDF2HMAC = None

from plain.postgres.lookups import Exact, IsNull
from plain.runtime import settings
from plain.utils.encoding import force_bytes

from plain import preflight

from .base import NOT_PROVIDED, Field, validate_none_only_default
from .json import JSONField
from .text import TextField

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.lookups import Lookup, Transform
    from plain.postgres.query_utils import Q
    from plain.preflight.results import PreflightResult

__all__ = [
    "EncryptedField",
    "EncryptedJSONField",
    "EncryptedTextField",
]

# Fixed salt for key derivation — changing this would invalidate all encrypted data.
# This is not secret; it ensures the derived encryption key is distinct from
# keys derived for other purposes (e.g., signing) even from the same SECRET_KEY.
_KDF_SALT = b"plain.postgres.fields.encrypted"

# Prefix for encrypted values in the database.
# Makes encrypted data self-describing and distinguishable from plaintext.
_ENCRYPTED_PREFIX = "$fernet$"


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key from an arbitrary secret string."""
    if PBKDF2HMAC is None:
        raise ImportError(
            "The 'cryptography' package is required to use encrypted fields. "
            "Install it with: pip install cryptography"
        )
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(force_bytes(secret)))


@cache
def _get_fernet(secret_key: str, fallbacks: tuple[str, ...]) -> MultiFernet:
    """Build a MultiFernet from the given secret key and fallbacks.

    The first key is used for encryption.
    All keys are used for decryption, enabling key rotation.
    Results are cached by (secret_key, fallbacks) so changing SECRET_KEY
    (e.g. in tests) produces a new MultiFernet automatically.
    """
    keys = [_derive_fernet_key(secret_key)]
    for fallback in fallbacks:
        keys.append(_derive_fernet_key(fallback))
    return MultiFernet([Fernet(k) for k in keys])


def _encrypt(value: str) -> str:
    """Encrypt a string and return a self-describing database value."""
    if value == "":
        return value
    f = _get_fernet(settings.SECRET_KEY, tuple(settings.SECRET_KEY_FALLBACKS))
    token = f.encrypt(force_bytes(value))
    return _ENCRYPTED_PREFIX + token.decode("ascii")


def _decrypt(value: str) -> str:
    """Decrypt a self-describing database value back to a string.

    Gracefully handles unencrypted values — if the value doesn't have
    the encryption prefix, it's returned as-is. This supports gradual
    migration from plaintext to encrypted fields.
    """
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value
    token = value[len(_ENCRYPTED_PREFIX) :]
    f = _get_fernet(settings.SECRET_KEY, tuple(settings.SECRET_KEY_FALLBACKS))
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise ValueError(
            "Could not decrypt field value. The SECRET_KEY (and SECRET_KEY_FALLBACKS) "
            "may have changed since this data was encrypted."
        )


# Shared tail explaining why encrypted fields reject value comparisons — used
# by every refusal, which all route through
# `EncryptedField._lookup_unsupported_message`.
_NON_DETERMINISTIC_EXPLANATION = (
    "ciphertext is non-deterministic. Use .is_null() instead."
)


class _EncryptedExact(Exact):
    """An exact lookup that rejects non-None right-hand values.

    None passes through so the ORM's exact-None → isnull rewrite in
    `build_lookup` still works. Any other value could only ever match nothing
    (ciphertext is non-deterministic), so it raises instead of silently
    returning no rows.
    """

    def __init__(self, lhs: Any, rhs: Any) -> None:
        if rhs is not None:
            # lhs.output_field is the encrypted field itself (the lookups.py
            # idiom). Its own sentence, not _lookup_unsupported_message's:
            # `filter()` *is* supported here, just not against a value, and
            # saying "does not support .filter()" would be wrong. Both share
            # the explanation tail below.
            raise TypeError(
                f"Encrypted field {lhs.output_field.name!r} cannot be filtered "
                f"by equality against a non-None value — "
                f"{_NON_DETERMINISTIC_EXPLANATION}"
            )
        super().__init__(lhs, rhs)


class EncryptedField[T](Field[T]):
    """Shared base for all encrypted fields, and the type to annotate them with.

    Owns the lookup surface (isnull and exact only — ciphertext is
    non-deterministic) and the preflight that blocks indexes and unique
    constraints. Also blocks the typed-query comparison methods.

    Annotate encrypted model fields with this rather than the plain ``Field``:

        api_key: EncryptedField[str] = types.EncryptedTextField(max_length=200)

    The annotation is what the type checker sees, so a plain ``Field[str]``
    would hide the ``Never``-typed blocks below and let
    ``Model.api_key.equals("x")`` type-check on its way to a runtime
    ``TypeError``. It is a ``Field[T]`` subclass, so the synthesized
    constructor types the field exactly as ``Field[T]`` would.

    Concrete encrypted fields mix this with the field they specialize
    (``TextField``, ``JSONField``), which supplies the column behavior.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Present only for the type checker. ty resolves `super().__init__` in
        # EncryptedJSONField through this class and lands on `Field.__init__`,
        # which takes no arguments, so without a signature here it rejects the
        # kwargs the concrete field forwards. At runtime this is a plain
        # cooperative passthrough and the MRO would reach the concrete field
        # either way.
        super().__init__(**kwargs)

    # The complete lookup surface, replacing the base field's registry.
    # isnull is obviously needed. exact is required so that `filter(field=None)`
    # works — the ORM resolves "exact" first and then rewrites None to isnull.
    # _EncryptedExact rejects non-None right-hand values, so the silent-no-rows
    # behavior on `filter(field='something')` is blocked too. The base classes
    # are named directly — inheriting the concrete field's registrations would
    # leak specialized lookups like JSONField's JSONExact, which compares
    # against the jsonb 'null' literal and defeats the None→isnull rewrite.
    # get_lookup()/get_transform() and registry consumers (e.g.
    # unsupported-lookup error suggestions) all resolve through this one dict.
    # A classmethod so both class-level and instance-level callers work.
    @classmethod
    def get_lookups(cls) -> dict[str, type[Lookup | Transform]]:
        return {"exact": _EncryptedExact, "isnull": IsNull}

    def get_transform(self, name: str) -> Callable[..., Transform] | None:
        # JSONField's get_transform falls back to KeyTransformFactory for any
        # name — key transforms would operate on ciphertext, so block them.
        return None

    def _build_q(self, method: str, suffix: str, value: Any) -> Q:
        """The one runtime guard. Every condition method on `Field` funnels
        through here, so blocking the ones that compare ciphertext takes a
        single override -- including conditions that don't exist yet.

        `isnull` is the only meaningful comparison: it reads the column's
        NULL-ness, not its contents.
        """
        if suffix != "isnull":
            raise TypeError(self._lookup_unsupported_message(method))
        return super()._build_q(method, suffix, value)

    if TYPE_CHECKING:
        # The static half of the same block. `Never` as the parameter type
        # rejects every call site; the return is `Never` (not `Q`) to reflect
        # that control never returns, and `Never` is assignable to `Q` so
        # `where(field.equals(...))` still type-checks at the use site with the
        # parameter error as the one that surfaces.
        #
        # Declarations only -- `_build_q` above is what raises. Keeping them
        # here means the static block and the runtime block can't drift into
        # disagreeing about *how* to refuse, only about which methods exist.
        def equals(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def not_equal(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def gt(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def gte(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def lt(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def lte(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def is_in(self, values: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def contains(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def icontains(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def startswith(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

        def endswith(self, value: Never) -> Never: ...  # ty: ignore[invalid-method-override]

    def _lookup_unsupported_message(self, method: str) -> str:
        assert self.name, (
            "Encrypted field must be attached to a model before its typed-query "
            "methods can produce a meaningful error message."
        )
        return (
            f"Encrypted field {self.name!r} does not support .{method}() — "
            f"{_NON_DETERMINISTIC_EXPLANATION}"
        )

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors: list[PreflightResult] = super().preflight(**kwargs)
        errors.extend(self._check_encrypted_constraints())
        return errors

    def _check_encrypted_constraints(self) -> list[PreflightResult]:
        errors: list[PreflightResult] = []
        if not hasattr(self, "model"):
            return errors

        field_name = self.name

        for constraint in self.model.model_options.constraints:
            constraint_fields = getattr(constraint, "fields", ())
            if field_name in constraint_fields:
                errors.append(
                    preflight.PreflightResult(
                        fix=(
                            f"'{self.model.__name__}.{field_name}' is an encrypted field "
                            f"and cannot be used in constraint '{constraint.name}'. "
                            "Encrypted values are non-deterministic."
                        ),
                        obj=self,
                        id="fields.encrypted_in_constraint",
                    )
                )

        for index in self.model.model_options.indexes:
            index_fields = getattr(index, "fields", ())
            # Strip ordering prefix (e.g., "-field_name" for descending)
            stripped_fields = [f.lstrip("-") for f in index_fields]
            if field_name in stripped_fields:
                errors.append(
                    preflight.PreflightResult(
                        fix=(
                            f"'{self.model.__name__}.{field_name}' is an encrypted field "
                            f"and cannot be used in index '{index.name}'. "
                            "Encrypted values are non-deterministic."
                        ),
                        obj=self,
                        id="fields.encrypted_in_index",
                    )
                )

        return errors


class EncryptedTextField[T: (str, str | None) = str](EncryptedField[T], TextField[T]):
    """A TextField that encrypts its value before storing in the database.

    Values are encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with a key
    derived from SECRET_KEY. The database column is always ``text`` regardless
    of max_length, since ciphertext length is unpredictable.

    max_length is enforced on the plaintext value (validation), not on the
    ciphertext stored in the database. Only ``default=""`` (with
    ``required=False``) is accepted — empty strings are stored as plaintext
    ``''``, so the empty value is the one default expressible as a column
    DEFAULT; anything else would need ciphertext, which is non-deterministic.
    """

    only_empty_default = True

    def __init__(
        self,
        *,
        max_length: int | None = None,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        # Deliberately narrower than TextField: no `choices` — exact lookups
        # on ciphertext are non-deterministic, so choice-based filtering would
        # silently match nothing.
        super().__init__(
            max_length=max_length,
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
        )

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        value = super().get_db_prep_value(value, connection, prepared)
        if value is None:
            return value
        return _encrypt(value)

    def from_db_value(
        self, value: Any, expression: Any, connection: DatabaseConnection
    ) -> str | None:
        if value is None:
            return value
        return _decrypt(value)


class EncryptedJSONField(EncryptedField[Any], JSONField):
    """A JSONField that encrypts its serialized value before storing in the database.

    The JSON value is serialized to a string, encrypted, and stored as text.
    On read, it's decrypted and deserialized back to a Python object.

    Deliberately narrower than JSONField: no *persistent* ``default`` — there is
    no empty plaintext value (even ``{}`` serializes to text that would need
    ciphertext, which is non-deterministic), so no literal column DEFAULT can be
    expressed. ``default=None`` is accepted on a nullable field, which stores
    nothing and only marks the field optional in the typed constructor.
    """

    db_type_sql = "text"

    # Ciphertext is non-deterministic, so there is no literal to put in the
    # column. This drives the autodetector's backfill guidance, which is only
    # reached for non-nullable fields -- where `None` could never backfill
    # anyway, so the `default=None` accepted below doesn't contradict it.
    accepts_persistent_default = False

    def __init__(
        self,
        *,
        encoder: type[json.JSONEncoder] | None = None,
        decoder: type[json.JSONDecoder] | None = None,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        # None-only, and not forwarded to DefaultableField -- exactly how the
        # ColumnField-direct fields (UUIDField, DateTimeField, ForeignKeyField)
        # model the same affordance.
        validate_none_only_default(self, default, allow_null=allow_null)
        super().__init__(
            encoder=encoder,
            decoder=decoder,
            required=required,
            allow_null=allow_null,
            validators=validators,
        )

    def adapt_json_db_value(self, value: Any) -> Any:
        # jsonb adaptation would emit jsonb — this column stores ciphertext.
        if value is None:
            return value
        return _encrypt(json.dumps(value, cls=self.encoder))

    def from_db_value(
        self, value: Any, expression: Any, connection: DatabaseConnection
    ) -> Any:
        if value is None:
            return value
        decrypted = _decrypt(value)
        try:
            return json.loads(decrypted, cls=self.decoder)
        except json.JSONDecodeError:
            raise ValueError(
                "Encrypted field contains data that is not valid JSON. "
                "The stored value may be corrupt."
            )
