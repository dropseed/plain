from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.models.expressions import Func
from plain.models.fields import Field
from plain.models.functions.mixins import (
    FixDecimalInputMixin,
    NumericOutputFieldMixin,
)
from plain.models.lookups import Transform

if TYPE_CHECKING:
    pass


class Abs(Transform):
    function = "ABS"
    lookup_name = "abs"


class ACos(NumericOutputFieldMixin, Transform):
    function = "ACOS"
    lookup_name = "acos"


class ASin(NumericOutputFieldMixin, Transform):
    function = "ASIN"
    lookup_name = "asin"


class ATan(NumericOutputFieldMixin, Transform):
    function = "ATAN"
    lookup_name = "atan"


class ATan2(NumericOutputFieldMixin, Func):
    function = "ATAN2"
    arity = 2


class Ceil(Transform):
    function = "CEILING"
    lookup_name = "ceil"


class Cos(NumericOutputFieldMixin, Transform):
    function = "COS"
    lookup_name = "cos"


class Cot(NumericOutputFieldMixin, Transform):
    function = "COT"
    lookup_name = "cot"


class Degrees(NumericOutputFieldMixin, Transform):
    function = "DEGREES"
    lookup_name = "degrees"


class Exp(NumericOutputFieldMixin, Transform):
    function = "EXP"
    lookup_name = "exp"


class Floor(Transform):
    function = "FLOOR"
    lookup_name = "floor"


class Ln(NumericOutputFieldMixin, Transform):
    function = "LN"
    lookup_name = "ln"


class Log(FixDecimalInputMixin, NumericOutputFieldMixin, Func):
    function = "LOG"
    arity = 2


class Mod(FixDecimalInputMixin, NumericOutputFieldMixin, Func):
    function = "MOD"
    arity = 2


class Pi(NumericOutputFieldMixin, Func):
    function = "PI"
    arity = 0


class Power(NumericOutputFieldMixin, Func):
    function = "POWER"
    arity = 2


class Radians(NumericOutputFieldMixin, Transform):
    function = "RADIANS"
    lookup_name = "radians"


class Random(NumericOutputFieldMixin, Func):
    function = "RANDOM"
    arity = 0

    def get_group_by_cols(self) -> list[Any]:
        return []


class Round(FixDecimalInputMixin, Transform):
    function = "ROUND"
    lookup_name = "round"
    arity = None  # Override Transform's arity=1 to enable passing precision.

    def __init__(self, expression: Any, precision: int = 0, **extra: Any) -> None:
        super().__init__(expression, precision, **extra)

    def _resolve_output_field(self) -> Field:
        source = self.get_source_expressions()[0]
        return source.output_field


class Sign(Transform):
    function = "SIGN"
    lookup_name = "sign"


class Sin(NumericOutputFieldMixin, Transform):
    function = "SIN"
    lookup_name = "sin"


class Sqrt(NumericOutputFieldMixin, Transform):
    function = "SQRT"
    lookup_name = "sqrt"


class Tan(NumericOutputFieldMixin, Transform):
    function = "TAN"
    lookup_name = "tan"
