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
        obj = "" if self.obj is None else self._obj_label()
        id_part = f"({self.id}) " if self.id else ""
        return f"{obj}: {id_part}{self.fix}"

    def _obj_label(self) -> str:
        if hasattr(self.obj, "model_options") and hasattr(
            self.obj.model_options, "label"
        ):
            # Duck type for model objects - use their meta label
            return self.obj.model_options.label
        return str(self.obj)

    def is_silenced(self) -> bool:
        if not self.id:
            return False
        silenced = settings.PREFLIGHT_SILENCED_RESULTS
        if self.id in silenced:
            return True
        # An "id:obj" entry silences the result for one specific object
        # (e.g. "postgres.missing_fk_index:insights.InsightEvent.sender_account")
        # while the same result id keeps warning everywhere else.
        return self.obj is not None and f"{self.id}:{self._obj_label()}" in silenced
