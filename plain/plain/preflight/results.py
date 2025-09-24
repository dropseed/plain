from plain.runtime import settings


class PreflightResult:
    def __init__(
        self, msg: str, *, hint: str = "", obj=None, id: str = "", warning: bool = False
    ):
        self.msg = msg
        self.hint = hint
        self.obj = obj
        self.id = id
        self.warning = warning

    def __eq__(self, other):
        return isinstance(other, self.__class__) and all(
            getattr(self, attr) == getattr(other, attr)
            for attr in ["msg", "hint", "obj", "id", "warning"]
        )

    def __str__(self):
        if self.obj is None:
            obj = ""
        elif hasattr(self.obj, "_meta") and hasattr(self.obj._meta, "label"):
            # Duck type for model objects - use their meta label
            obj = self.obj._meta.label
        else:
            obj = str(self.obj)
        id_part = f"({self.id}) " if self.id else ""
        hint_part = f"\n\tHINT: {self.hint}" if self.hint else ""
        return f"{obj}: {id_part}{self.msg}{hint_part}"

    def is_silenced(self):
        return self.id and self.id in settings.PREFLIGHT_SILENCED_RESULTS
