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

    def silenced_by(self) -> list[str]:
        """The `PREFLIGHT_SILENCED_RESULTS` entries that match this result.

        A bare entry matches the result id; an "id:obj" entry matches the
        result for one specific object (e.g.
        "postgres.missing_fk_index:insights.InsightEvent.sender_account")
        while the same result id keeps warning everywhere else.
        """
        if not self.id:
            return []
        silenced = settings.PREFLIGHT_SILENCED_RESULTS
        matched = []
        if self.id in silenced:
            matched.append(self.id)
        if self.obj is not None:
            qualified = f"{self.id}:{self._obj_label()}"
            if qualified in silenced:
                matched.append(qualified)
        return matched

    def is_silenced(self) -> bool:
        return bool(self.silenced_by())


def unused_silenced_results(results: list[PreflightResult]) -> list[str]:
    """`PREFLIGHT_SILENCED_RESULTS` entries that matched none of `results`.

    An unused entry is either a typo or stale — the issue it silenced has
    been fixed. Only meaningful when `results` came from a full run
    (deploy checks included); a partial run skips checks whose entries
    would then look unused.
    """
    if not settings.PREFLIGHT_SILENCED_RESULTS:
        return []
    used: set[str] = set()
    for result in results:
        used.update(result.silenced_by())
    return [entry for entry in settings.PREFLIGHT_SILENCED_RESULTS if entry not in used]
