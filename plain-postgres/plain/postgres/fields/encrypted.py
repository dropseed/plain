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

from plain import exceptions, preflight
from plain.runtime import settings
from plain.utils.encoding import force_bytes

from . import Field

if TYPE_CHECKING:
    from collections.abc import Callable

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


# isnull is obviously needed. exact is required so that `filter(field=None)`
# works — the ORM resolves "exact" first and then rewrites None to isnull.
# Exact lookups on non-None values will silently return no results (since
# ciphertext is non-deterministic), but blocking exact entirely would break
# the None/isnull path.
_ALLOWED_LOOKUPS = {"isnull", "exact"}


class EncryptedFieldMixin:
    """Shared behavior for all encrypted fields.

    Blocks lookups (except isnull and exact) since encrypted values are non-deterministic.
    Errors at preflight if the field is used in indexes or unique constraints.

    Must be used with Field as a co-base class.
    """

    # Type hints for attributes provided by Field (the required co-base class)
    name: str
    model: Any

    def get_lookup(self, lookup_name: str) -> type[Lookup] | None:
        if lookup_name not in _ALLOWED_LOOKUPS:
            return None
        get_lookup = getattr(super(), "get_lookup")
        return get_lookup(lookup_name)

    def get_transform(
        self, lookup_name: str
    ) -> type[Transform] | Callable[..., Any] | None:
        return None

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


class EncryptedTextField(EncryptedFieldMixin, Field[str]):
    """A text field that encrypts its value before storing in the database.

    Values are encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with a key
    derived from SECRET_KEY. The database column is always ``text`` regardless
    of max_length, since ciphertext length is unpredictable.

    max_length is enforced on the plaintext value (validation), not on the
    ciphertext stored in the database.
    """

    db_type_sql = "text"
    description = "Encrypted text"

    def __init__(self, *, max_length: int | None = None, **kwargs: Any):
        self.max_length = max_length
        super().__init__(**kwargs)

    def to_python(self, value: Any) -> str | None:
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def validate(self, value: Any, model_instance: Any) -> None:
        super().validate(value, model_instance)
        if (
            self.max_length is not None
            and value is not None
            and len(value) > self.max_length
        ):
            raise exceptions.ValidationError(
                f"Ensure this value has at most {self.max_length} characters (it has {len(value)}).",
                code="max_length",
            )

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return value
        return self.to_python(value)

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

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        # Override the path rewrite from Field.deconstruct() which would
        # shorten "plain.postgres.fields.encrypted" to "plain.postgres.encrypted"
        # (a module that doesn't exist).
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        return name, path, args, kwargs

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)
        errors.extend(self._check_encrypted_constraints())
        return errors


class EncryptedJSONField(EncryptedFieldMixin, Field):
    """A JSONField that encrypts its serialized value before storing in the database.

    The JSON value is serialized to a string, encrypted, and stored as text.
    On read, it's decrypted and deserialized back to a Python object.
    """

    db_type_sql = "text"
    empty_strings_allowed = False
    description = "Encrypted JSON"
    default_error_messages = {
        "invalid": "Value must be valid JSON.",
    }
    _default_fix = ("dict", "{}")

    def __init__(
        self,
        *,
        encoder: type[json.JSONEncoder] | None = None,
        decoder: type[json.JSONDecoder] | None = None,
        **kwargs: Any,
    ):
        if encoder and not callable(encoder):
            raise ValueError("The encoder parameter must be a callable object.")
        if decoder and not callable(decoder):
            raise ValueError("The decoder parameter must be a callable object.")
        self.encoder = encoder
        self.decoder = decoder
        super().__init__(**kwargs)

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        # Override the path rewrite from Field.deconstruct() which would
        # shorten to a nonexistent module (same pattern as EncryptedTextField).
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        if self.encoder is not None:
            kwargs["encoder"] = self.encoder
        if self.decoder is not None:
            kwargs["decoder"] = self.decoder
        return name, path, args, kwargs

    def validate(self, value: Any, model_instance: Any) -> None:
        super().validate(value, model_instance)
        try:
            json.dumps(value, cls=self.encoder)
        except TypeError:
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        value = super().get_db_prep_value(value, connection, prepared)
        if value is None:
            return value
        json_str = json.dumps(value, cls=self.encoder)
        return _encrypt(json_str)

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

    def _check_default(self) -> list[PreflightResult]:
        if (
            self.has_default()
            and self.default is not None
            and not callable(self.default)
        ):
            return [
                preflight.PreflightResult(
                    fix=(
                        f"{self.__class__.__name__} default should be a callable instead of an instance "
                        "so that it's not shared between all field instances. "
                        "Use a callable instead, e.g., use `{}` instead of "
                        "`{}`.".format(*self._default_fix)
                    ),
                    obj=self,
                    id="fields.encrypted_mutable_default",
                    warning=True,
                )
            ]
        else:
            return []

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)
        errors.extend(self._check_default())
        errors.extend(self._check_encrypted_constraints())
        return errors
