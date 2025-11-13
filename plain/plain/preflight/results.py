from __future__ import annotations

from typing import Any

from plain.runtime import settings


class PreflightResult:
    def __init__(
        self, *, fix: str, id: str, obj: Any = None, warning: bool = False
    ) -> None:
        self.fix = fix
        self.obj = obj
        self.id = id
        self.warning = warning

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and all(
            getattr(self, attr) == getattr(other, attr)
            for attr in ["fix", "obj", "id", "warning"]
        )

    def __str__(self) -> str:
        if self.obj is None:
            obj = ""
        elif hasattr(self.obj, "model_options") and hasattr(
            self.obj.model_options, "label"
        ):
            # Duck type for model objects - use their meta label
            obj = self.obj.model_options.label
        else:
            obj = str(self.obj)
        id_part = f"({self.id}) " if self.id else ""
        return f"{obj}: {id_part}{self.fix}"

    def is_silenced(self) -> bool:
        return bool(self.id and self.id in settings.PREFLIGHT_SILENCED_RESULTS)
