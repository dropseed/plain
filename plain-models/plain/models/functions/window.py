from __future__ import annotations

from typing import Any

from plain.models.expressions import Func
from plain.models.fields import Field, FloatField, IntegerField

__all__ = [
    "CumeDist",
    "DenseRank",
    "FirstValue",
    "Lag",
    "LastValue",
    "Lead",
    "NthValue",
    "Ntile",
    "PercentRank",
    "Rank",
    "RowNumber",
]


class CumeDist(Func):
    function = "CUME_DIST"
    output_field = FloatField()
    window_compatible = True


class DenseRank(Func):
    function = "DENSE_RANK"
    output_field = IntegerField()
    window_compatible = True


class FirstValue(Func):
    arity = 1
    function = "FIRST_VALUE"
    window_compatible = True


class LagLeadFunction(Func):
    window_compatible = True

    def __init__(
        self, expression: Any, offset: int = 1, default: Any = None, **extra: Any
    ) -> None:
        if expression is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a non-null source expression."
            )
        if offset is None or offset <= 0:
            raise ValueError(
                f"{self.__class__.__name__} requires a positive integer for the offset."
            )
        args = (expression, offset)
        if default is not None:
            args += (default,)
        super().__init__(*args, **extra)

    def _resolve_output_field(self) -> Field:
        sources = self.get_source_expressions()
        return sources[0].output_field


class Lag(LagLeadFunction):
    function = "LAG"


class LastValue(Func):
    arity = 1
    function = "LAST_VALUE"
    window_compatible = True


class Lead(LagLeadFunction):
    function = "LEAD"


class NthValue(Func):
    function = "NTH_VALUE"
    window_compatible = True

    def __init__(self, expression: Any, nth: int = 1, **extra: Any) -> None:
        if expression is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a non-null source expression."
            )
        if nth is None or nth <= 0:
            raise ValueError(
                f"{self.__class__.__name__} requires a positive integer as for nth."
            )
        super().__init__(expression, nth, **extra)

    def _resolve_output_field(self) -> Field:
        sources = self.get_source_expressions()
        return sources[0].output_field


class Ntile(Func):
    function = "NTILE"
    output_field = IntegerField()
    window_compatible = True

    def __init__(self, num_buckets: int = 1, **extra: Any) -> None:
        if num_buckets <= 0:
            raise ValueError("num_buckets must be greater than 0.")
        super().__init__(num_buckets, **extra)


class PercentRank(Func):
    function = "PERCENT_RANK"
    output_field = FloatField()
    window_compatible = True


class Rank(Func):
    function = "RANK"
    output_field = IntegerField()
    window_compatible = True


class RowNumber(Func):
    function = "ROW_NUMBER"
    output_field = IntegerField()
    window_compatible = True
