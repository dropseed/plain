"""Value types — a Python type a column round-trips through.

``types.TextField(value_type=X)`` and ``types.JSONField(value_type=X)`` make
a column carry ``X`` instead of its primitive: a read rebuilds an ``X``, a
write unwraps one, and anything that isn't an ``X`` is refused. That lets a
package or an app own a value's behavior without subclassing a field class —
which is the one extension axis typed construction can support, because PEP
681 only honors field specifiers that ``plain.postgres`` itself declares.

The column type is unaffected: a ``value_type`` text column is still ``text``,
a ``value_type`` JSON column is still ``jsonb``, and migrations never see the
kwarg at all.

The descriptor is symmetric — ``Field[X]`` both gets and sets an ``X``. There
is no lenient setter that builds an ``X`` out of a primitive: whatever
constructs the value (a form field, a factory classmethod) is also where its
validation belongs, which is why the protocol is only these two methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, Self

from .base import DATABASE_DEFAULT

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.postgres.connection import DatabaseConnection

__all__ = ["ValueType", "ValueTypeMixin"]


class ValueType(Protocol):
    """The two-method contract a ``value_type=`` column round-trips through.

    ``from_db`` builds the Python value out of what the column returned;
    ``to_db`` returns what goes back into the column (a ``str`` for a text
    column, a JSON-serializable object for a JSON one).
    """

    @classmethod
    def from_db(cls, raw: Any, /) -> Self: ...

    def to_db(self) -> Any: ...


class ValueTypeMixin:
    """The ``value_type=`` plumbing, shared by the fields that accept it.

    Mixed in ahead of the field class so ``get_db_converters`` composes: a
    JSON column decodes its raw text first and hands the decoded object to
    ``from_db``.
    """

    # The declared Python type, or None for an ordinary column. Read by
    # anything that needs to know a column is opaque — the form layer refuses
    # to derive a form field from one.
    value_type: type[ValueType] | None = None

    def get_db_converters(
        self, connection: DatabaseConnection
    ) -> list[Callable[..., Any]]:
        converters = super().get_db_converters(connection)  # ty: ignore[unresolved-attribute]
        if self.value_type is not None:
            converters.append(self._convert_value_type)
        return converters

    def _convert_value_type(
        self, value: Any, expression: Any, connection: DatabaseConnection
    ) -> Any:
        """Row converter: rebuild the value type from what the column returned."""
        assert self.value_type is not None
        if value is None:
            return None
        return self.value_type.from_db(value)

    def value_type_to_db(self, value: Any) -> Any:
        """Unwrap a value on its way to the column.

        Refuses anything that isn't an instance of the declared ``value_type``.
        This is the one place a raw primitive is turned away, so it covers
        every write and lookup path alike — ``instance.update()``,
        ``QuerySet.update(col=...)``, and ``filter(col=...)``.
        """
        assert self.value_type is not None
        if value is None or value is DATABASE_DEFAULT or hasattr(value, "as_sql"):
            return value
        if not isinstance(value, self.value_type):
            name = self.value_type.__name__
            raise TypeError(
                f"{self} takes a {name}, not a {type(value).__name__}. "
                f"Build one with {name} and pass that."
            )
        return value.to_db()
