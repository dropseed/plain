"""
Type stubs for typed password fields.

These stubs tell type checkers that field constructors return primitive types,
enabling typed model definitions like:
    password: str = types.PasswordField()

At runtime, these are Field instances (descriptors), but type checkers see the primitives.

The return type is conditional on allow_null:
- allow_null=False (default) returns str
- allow_null=True returns str | None
"""

from collections.abc import Callable, Sequence
from typing import Any, Literal, overload

# PasswordField extends CharField with password-specific hashing
@overload
def PasswordField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def PasswordField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
