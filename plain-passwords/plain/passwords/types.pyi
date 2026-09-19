"""
Type stubs for the typed PasswordField.

Like the core `plain.postgres.types` field stubs, these return the typed
descriptor `Field[T]` so a model can annotate the field with `Field[str]`:

    password: Field[str] = PasswordField()

`Field.__get__`'s overloads then give the field reference at the class level
and the `str` value at instance access. The return type tracks nullability:
- allow_null=False (default) -> Field[str]
- allow_null=True            -> Field[str | None]
"""

from collections.abc import Callable, Sequence
from typing import Any, Literal, overload

from plain.postgres.fields.base import Field as _Field

# PasswordField extends TextField with password-specific hashing
@overload
def PasswordField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
) -> _Field[str | None]: ...
@overload
def PasswordField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
) -> _Field[str]: ...
