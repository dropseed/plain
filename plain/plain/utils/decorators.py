"Functions that help with dynamically creating decorators for views."

from __future__ import annotations

from typing import Any


class classonlymethod(classmethod):
    def __get__(self, instance: object | None, cls: type | None = None) -> Any:
        if instance is not None:
            raise AttributeError(
                "This method is available only on the class, not on instances."
            )
        return super().__get__(instance, cls)
