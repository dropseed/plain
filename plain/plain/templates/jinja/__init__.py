from plain.runtime import settings
from plain.utils.functional import LazyObject
from plain.utils.module_loading import import_string

from .defaults import create_default_environment, get_template_dirs


class JinjaEnvironment(LazyObject):
    def _setup(self):
        environment_setting = settings.JINJA_ENVIRONMENT

        if isinstance(environment_setting, str):
            environment = import_string(environment_setting)()
        else:
            environment = environment_setting()

        self._wrapped = environment


environment = JinjaEnvironment()

__all__ = ["environment", "create_default_environment", "get_template_dirs"]
