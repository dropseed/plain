"""
Typed field imports for better IDE and type checker support.

This module provides password-specific field classes with a companion .pyi
stub file that makes type checkers interpret field assignments as their
primitive Python types.

Usage:
    from plain.postgres import Field, types
    from plain.passwords.types import PasswordField

    @postgres.register_model
    class User(postgres.Model):
        email: Field[str] = types.EmailField()
        password: Field[str] = PasswordField()
"""

from plain.passwords.models import PasswordField

__all__ = ["PasswordField"]
