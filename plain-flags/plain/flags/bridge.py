from plain.runtime import settings

from . import exceptions
from .flags import Flag


def get_flags_module():
    flags_module = settings.FLAGS_MODULE

    try:
        return __import__(flags_module)
    except ImportError as e:
        raise exceptions.FlagImportError(
            f"Could not import {flags_module} module"
        ) from e


def get_flag_class(flag_name: str) -> Flag:
    flags_module = get_flags_module()

    try:
        flag_class = getattr(flags_module, flag_name)
    except AttributeError as e:
        raise exceptions.FlagImportError(
            f"Could not find {flag_name} in {flags_module} module"
        ) from e

    return flag_class
