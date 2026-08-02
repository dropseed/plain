from __future__ import annotations

import base64
import json
from functools import cache
from typing import TYPE_CHECKING, Any

try:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    Fernet = None  # ty: ignore[invalid-assignment]
    InvalidToken = None  # ty: ignore[invalid-assignment]
    MultiFernet = None  # ty: ignore[invalid-assignment]
    hashes = None  # ty: ignore[invalid-assignment]
    PBKDF2HMAC = None  # ty: ignore[invalid-assignment]

from plain import preflight
from plain.postgres.lookups import Exact, IsNull
from plain.runtime import settings
from plain.utils.encoding import force_bytes

from .base import NOT_PROVIDED
from .json import JSONField
from .text import TextField

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.lookups import Lookup, Transform
    from plain.preflight.results import PreflightResult

__all__ = [
    "EncryptedTextField",
    "EncryptedJSONField",
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


class EncryptedFieldMixin:
    """Shared behavior for all encrypted fields.

    Owns the lookup surface (isnull and exact only — ciphertext is
    non-deterministic) and the preflight that blocks indexes and unique
    constraints.

    Must be used with Field as a co-base class.
    """

    # Type hints for attributes provided by Field (the required co-base class)
    name: str
    model: Any

    # The complete lookup surface, replacing the base field's registry.
    # isnull is obviously needed. exact is required so that `filter(field=None)`
    # works — the ORM resolves "exact" first and then rewrites None to isnull.
    # Exact lookups on non-None values will silently return no results (since
    # ciphertext is non-deterministic), but blocking exact entirely would break
    # the None/isnull path. The base classes are named directly — inheriting
    # the concrete field's registrations would leak specialized lookups like
    # JSONField's JSONExact, which compares against the jsonb 'null' literal
    # and defeats the None→isnull rewrite. get_lookup()/get_transform() and
    # registry consumers (e.g. unsupported-lookup error suggestions) all
    # resolve through this one dict. A classmethod so both class-level and
    # instance-level callers work.
    @classmethod
    def get_lookups(cls) -> dict[str, type[Lookup | Transform]]:
        return {"exact": Exact, "isnull": IsNull}

    def get_transform(self, name: str) -> Callable[..., Transform] | None:
        # JSONField's get_transform falls back to KeyTransformFactory for any
        # name — key transforms would operate on ciphertext, so block them.
        return None

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors: list[PreflightResult] = super().preflight(**kwargs)  # ty: ignore[unresolved-attribute]
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


class EncryptedTextField[T: (str, str | None) = str](EncryptedFieldMixin, TextField[T]):
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


class EncryptedJSONField(EncryptedFieldMixin, JSONField):
    """A JSONField that encrypts its serialized value before storing in the database.

    The JSON value is serialized to a string, encrypted, and stored as text.
    On read, it's decrypted and deserialized back to a Python object.
    """

    db_type_sql = "text"
    accepts_default = False

    def __init__(
        self,
        *,
        encoder: type[json.JSONEncoder] | None = None,
        decoder: type[json.JSONDecoder] | None = None,
        required: bool = True,
        allow_null: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        # Deliberately narrower than JSONField: no `default` — there is no
        # empty plaintext value (even {} serializes to text that would need
        # ciphertext, which is non-deterministic), so no literal column
        # DEFAULT can be expressed.
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
