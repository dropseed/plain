from typing import Union

import pytest

from plain.exceptions import ImproperlyConfigured
from plain.runtime import Secret, settings
from plain.runtime.user_settings import _parse_env_value


def test_user_settings():
    # Relies on env vars in conftest.py
    assert settings.DEFAULT_SETTING == "unchanged default"
    assert settings.EXPLICIT_SETTING == "explicitly changed"
    assert settings.ENV_SETTING == 1
    assert settings.EXPLICIT_OVERRIDDEN_SETTING == "env value"


def test_parse_env_value_str_passthrough():
    # Bare strings are returned as-is, no JSON quoting required.
    assert _parse_env_value("dark", str, "FOO") == "dark"
    assert _parse_env_value("", str, "FOO") == ""


def test_parse_env_value_bool():
    for truthy in ("true", "TRUE", "1", "yes"):
        assert _parse_env_value(truthy, bool, "FOO") is True
    for falsy in ("false", "0", "no", ""):
        assert _parse_env_value(falsy, bool, "FOO") is False


def test_parse_env_value_int_via_json():
    assert _parse_env_value("42", int, "FOO") == 42


def test_parse_env_value_list_and_dict_via_json():
    assert _parse_env_value('["a", "b"]', list[str], "FOO") == ["a", "b"]
    assert _parse_env_value('{"k": 1}', dict[str, int], "FOO") == {"k": 1}


def test_parse_env_value_invalid_json_raises():
    with pytest.raises(ImproperlyConfigured, match="Invalid JSON"):
        _parse_env_value("not-json", list[str], "FOO")


def test_parse_env_value_missing_annotation_raises():
    with pytest.raises(ImproperlyConfigured, match="Type hint required"):
        _parse_env_value("anything", None, "FOO")


def test_parse_env_value_secret_unwraps_inner_type():
    # Secret[str] should accept a bare string just like str.
    assert _parse_env_value("hunter2", Secret[str], "FOO") == "hunter2"
    # Secret[int] should still parse as int via JSON.
    assert _parse_env_value("42", Secret[int], "FOO") == 42


def test_parse_env_value_nullable_str_unwraps():
    # `str | None` accepts a bare string and treats empty as None.
    assert _parse_env_value("dark", str | None, "FOO") == "dark"
    assert _parse_env_value("", str | None, "FOO") is None
    # `Optional[str]` (typing.Union form) behaves the same.
    assert _parse_env_value("dark", Union[str, None], "FOO") == "dark"  # noqa: UP007
    assert _parse_env_value("", Union[str, None], "FOO") is None  # noqa: UP007


def test_parse_env_value_nullable_int_unwraps():
    # Empty string clears to None; non-empty parses as the inner type.
    assert _parse_env_value("", int | None, "FOO") is None
    assert _parse_env_value("42", int | None, "FOO") == 42
