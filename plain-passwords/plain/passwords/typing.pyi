"""Type stubs for password field.

PasswordField is a CharField subclass, so we alias to CharField's stub.
"""

from plain.models.fields.typing import CharField as PasswordField

__all__ = ["PasswordField"]
