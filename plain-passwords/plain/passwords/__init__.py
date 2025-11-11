from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .typing import PasswordField
else:
    from .models import PasswordField

__all__ = ["PasswordField"]
