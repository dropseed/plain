"""
Typed field imports for better IDE and type checker support.

This module provides password-specific field classes with a companion .pyi
stub file that makes type checkers interpret field assignments as their
primitive Python types.

Usage:
    from plain.passwords.types import PasswordField

    @models.register_model
    class User(models.Model):
        email: str = types.EmailField()
        password: str = PasswordField()

This is optional - you can continue using untyped field definitions.
"""

from plain.passwords.models import PasswordField

__all__ = ["PasswordField"]
