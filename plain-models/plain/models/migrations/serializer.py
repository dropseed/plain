from __future__ import annotations

import builtins
import collections.abc
import datetime
import decimal
import enum
import functools
import math
import os
import pathlib
import re
import types
import uuid
from typing import Any

from plain.models.base import Model
from plain.models.enums import Choices
from plain.models.fields import Field
from plain.models.migrations.operations.base import Operation
from plain.models.migrations.utils import COMPILED_REGEX_TYPE, RegexObject
from plain.runtime import SettingsReference
from plain.utils.functional import LazyObject, Promise


class BaseSerializer:
    def __init__(self, value: Any) -> None:
        self.value = value

    def serialize(self) -> tuple[str, set[str]]:
        raise NotImplementedError(
            "Subclasses of BaseSerializer must implement the serialize() method."
        )


class BaseSequenceSerializer(BaseSerializer):
    def _format(self) -> str:
        raise NotImplementedError(
            "Subclasses of BaseSequenceSerializer must implement the _format() method."
        )

    def serialize(self) -> tuple[str, set[str]]:
        imports: set[str] = set()
        strings = []
        for item in self.value:
            item_string, item_imports = serializer_factory(item).serialize()
            imports.update(item_imports)
            strings.append(item_string)
        value = self._format()
        return value % (", ".join(strings)), imports


class BaseSimpleSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return repr(self.value), set()


class ChoicesSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return serializer_factory(self.value.value).serialize()


class DateTimeSerializer(BaseSerializer):
    """For datetime.*, except datetime.datetime."""

    def serialize(self) -> tuple[str, set[str]]:
        return repr(self.value), {"import datetime"}


class DatetimeDatetimeSerializer(BaseSerializer):
    """For datetime.datetime."""

    def serialize(self) -> tuple[str, set[str]]:
        if self.value.tzinfo is not None and self.value.tzinfo != datetime.UTC:
            self.value = self.value.astimezone(datetime.UTC)
        imports = ["import datetime"]
        return repr(self.value), set(imports)


class DecimalSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return repr(self.value), {"from decimal import Decimal"}


class DeconstructableSerializer(BaseSerializer):
    @staticmethod
    def serialize_deconstructed(
        path: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[str, set[str]]:
        name, imports = DeconstructableSerializer._serialize_path(path)
        strings = []
        for arg in args:
            arg_string, arg_imports = serializer_factory(arg).serialize()
            strings.append(arg_string)
            imports.update(arg_imports)
        for kw, arg in sorted(kwargs.items()):
            arg_string, arg_imports = serializer_factory(arg).serialize()
            imports.update(arg_imports)
            strings.append(f"{kw}={arg_string}")
        return "{}({})".format(name, ", ".join(strings)), imports

    @staticmethod
    def _serialize_path(path: str) -> tuple[str, set[str]]:
        module, name = path.rsplit(".", 1)
        if module == "plain.models":
            imports: set[str] = {"from plain import models"}
            name = f"models.{name}"
        else:
            imports = {f"import {module}"}
            name = path
        return name, imports

    def serialize(self) -> tuple[str, set[str]]:
        return self.serialize_deconstructed(*self.value.deconstruct())


class DictionarySerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        imports: set[str] = set()
        strings = []
        for k, v in sorted(self.value.items()):
            k_string, k_imports = serializer_factory(k).serialize()
            v_string, v_imports = serializer_factory(v).serialize()
            imports.update(k_imports)
            imports.update(v_imports)
            strings.append((k_string, v_string))
        return "{{{}}}".format(", ".join(f"{k}: {v}" for k, v in strings)), imports


class EnumSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        enum_class = self.value.__class__
        module = enum_class.__module__
        if issubclass(enum_class, enum.Flag):
            members = list(self.value)
        else:
            members = (self.value,)
        return (
            " | ".join(
                [
                    f"{module}.{enum_class.__qualname__}[{item.name!r}]"
                    for item in members
                ]
            ),
            {f"import {module}"},
        )


class FloatSerializer(BaseSimpleSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        if math.isnan(self.value) or math.isinf(self.value):
            return f'float("{self.value}")', set()
        return super().serialize()


class FrozensetSerializer(BaseSequenceSerializer):
    def _format(self) -> str:
        return "frozenset([%s])"


class FunctionTypeSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        if getattr(self.value, "__self__", None) and isinstance(
            self.value.__self__, type
        ):
            klass = self.value.__self__
            module = klass.__module__
            return f"{module}.{klass.__name__}.{self.value.__name__}", {
                f"import {module}"
            }
        # Further error checking
        if self.value.__name__ == "<lambda>":
            raise ValueError("Cannot serialize function: lambda")
        if self.value.__module__ is None:
            raise ValueError(f"Cannot serialize function {self.value!r}: No module")

        module_name = self.value.__module__

        if "<" not in self.value.__qualname__:  # Qualname can include <locals>
            return f"{module_name}.{self.value.__qualname__}", {
                f"import {self.value.__module__}"
            }

        raise ValueError(
            f"Could not find function {self.value.__name__} in {module_name}.\n"
        )


class FunctoolsPartialSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        # Serialize functools.partial() arguments
        func_string, func_imports = serializer_factory(self.value.func).serialize()
        args_string, args_imports = serializer_factory(self.value.args).serialize()
        keywords_string, keywords_imports = serializer_factory(
            self.value.keywords
        ).serialize()
        # Add any imports needed by arguments
        imports: set[str] = {
            "import functools",
            *func_imports,
            *args_imports,
            *keywords_imports,
        }
        return (
            f"functools.{self.value.__class__.__name__}({func_string}, *{args_string}, **{keywords_string})",
            imports,
        )


class IterableSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        imports: set[str] = set()
        strings = []
        for item in self.value:
            item_string, item_imports = serializer_factory(item).serialize()
            imports.update(item_imports)
            strings.append(item_string)
        # When len(strings)==0, the empty iterable should be serialized as
        # "()", not "(,)" because (,) is invalid Python syntax.
        value = "(%s)" if len(strings) != 1 else "(%s,)"
        return value % (", ".join(strings)), imports


class ModelFieldSerializer(DeconstructableSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        attr_name, path, args, kwargs = self.value.deconstruct()
        return self.serialize_deconstructed(path, args, kwargs)


class OperationSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        from plain.models.migrations.writer import OperationWriter

        string, imports = OperationWriter(self.value, indentation=0).serialize()
        # Nested operation, trailing comma is handled in upper OperationWriter._write()
        return string.rstrip(","), imports


class PathLikeSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return repr(os.fspath(self.value)), set()


class PathSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        # Convert concrete paths to pure paths to avoid issues with migrations
        # generated on one platform being used on a different platform.
        prefix = "Pure" if isinstance(self.value, pathlib.Path) else ""
        return f"pathlib.{prefix}{self.value!r}", {"import pathlib"}


class RegexSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        regex_pattern, pattern_imports = serializer_factory(
            self.value.pattern
        ).serialize()
        # Turn off default implicit flags (e.g. re.U) because regexes with the
        # same implicit and explicit flags aren't equal.
        flags = self.value.flags ^ re.compile("").flags
        regex_flags, flag_imports = serializer_factory(flags).serialize()
        imports: set[str] = {"import re", *pattern_imports, *flag_imports}
        args = [regex_pattern]
        if flags:
            args.append(regex_flags)
        return "re.compile({})".format(", ".join(args)), imports


class SequenceSerializer(BaseSequenceSerializer):
    def _format(self) -> str:
        return "[%s]"


class SetSerializer(BaseSequenceSerializer):
    def _format(self) -> str:
        # Serialize as a set literal except when value is empty because {}
        # is an empty dict.
        return "{%s}" if self.value else "set(%s)"


class SettingsReferenceSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return f"settings.{self.value.setting_name}", {
            "from plain.runtime import settings"
        }


class TupleSerializer(BaseSequenceSerializer):
    def _format(self) -> str:
        # When len(value)==0, the empty tuple should be serialized as "()",
        # not "(,)" because (,) is invalid Python syntax.
        return "(%s)" if len(self.value) != 1 else "(%s,)"


class TypeSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        special_cases = [
            (Model, "models.Model", ["from plain import models"]),
            (types.NoneType, "types.NoneType", ["import types"]),
        ]
        for case, string, imports in special_cases:
            if case is self.value:
                return string, set(imports)
        if hasattr(self.value, "__module__"):
            module = self.value.__module__
            if module == builtins.__name__:
                return self.value.__name__, set()
            else:
                return f"{module}.{self.value.__qualname__}", {f"import {module}"}
        return "", set()


class UUIDSerializer(BaseSerializer):
    def serialize(self) -> tuple[str, set[str]]:
        return f"uuid.{repr(self.value)}", {"import uuid"}


class Serializer:
    _registry = {
        # Some of these are order-dependent.
        frozenset: FrozensetSerializer,
        list: SequenceSerializer,
        set: SetSerializer,
        tuple: TupleSerializer,
        dict: DictionarySerializer,
        Choices: ChoicesSerializer,
        enum.Enum: EnumSerializer,
        datetime.datetime: DatetimeDatetimeSerializer,
        (datetime.date, datetime.timedelta, datetime.time): DateTimeSerializer,
        SettingsReference: SettingsReferenceSerializer,
        float: FloatSerializer,
        (bool, int, types.NoneType, bytes, str, range): BaseSimpleSerializer,
        decimal.Decimal: DecimalSerializer,
        (functools.partial, functools.partialmethod): FunctoolsPartialSerializer,
        (
            types.FunctionType,
            types.BuiltinFunctionType,
            types.MethodType,
        ): FunctionTypeSerializer,
        collections.abc.Iterable: IterableSerializer,
        (COMPILED_REGEX_TYPE, RegexObject): RegexSerializer,
        uuid.UUID: UUIDSerializer,
        pathlib.PurePath: PathSerializer,
        os.PathLike: PathLikeSerializer,
    }

    @classmethod
    def register(cls, type_: type[Any], serializer: type[BaseSerializer]) -> None:
        if not issubclass(serializer, BaseSerializer):
            raise ValueError(
                f"'{serializer.__name__}' must inherit from 'BaseSerializer'."
            )
        cls._registry[type_] = serializer


def serializer_factory(value: Any) -> BaseSerializer:
    if isinstance(value, Promise):
        value = str(value)
    elif isinstance(value, LazyObject):
        # The unwrapped value is returned as the first item of the arguments
        # tuple.
        value = value.__reduce__()[1][0]

    if isinstance(value, Field):
        return ModelFieldSerializer(value)
    if isinstance(value, Operation):
        return OperationSerializer(value)
    if isinstance(value, type):
        return TypeSerializer(value)
    # Anything that knows how to deconstruct itself.
    if hasattr(value, "deconstruct"):
        return DeconstructableSerializer(value)
    for type_, serializer_cls in Serializer._registry.items():
        if isinstance(value, type_):
            return serializer_cls(value)
    raise ValueError(
        f"Cannot serialize: {value!r}\nThere are some values Plain cannot serialize into "
        "migration files."
    )
