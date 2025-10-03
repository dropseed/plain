from __future__ import annotations

from typing import Any

from .hashers import check_password, hash_password


def check_user_password(user: Any, password: str) -> bool:
    # Run the default password hasher once to reduce the timing
    # difference between an existing and a nonexistent user (#20760).
    hash_password(password)

    # Update the stored hashed password if the hashing algorithm changed
    def setter(raw_password: str) -> None:
        user.password = raw_password
        user.save(update_fields=["password"])

    password_is_correct = check_password(password, user.password, setter)

    return password_is_correct
