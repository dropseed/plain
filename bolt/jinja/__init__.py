from bolt.runtime import settings
from bolt.utils.functional import LazyObject
from bolt.utils.module_loading import import_string

from .defaults import create_default_environment, get_template_dirs


class JinjaEnvironment(LazyObject):
    def _setup(self):
        environment_setting = getattr(
            settings, "JINJA_ENVIRONMENT", create_default_environment
        )

        if isinstance(environment_setting, str):
            environment = import_string(environment_setting)()
        else:
            environment = environment_setting()

        self._wrapped = environment


environment = JinjaEnvironment()

__all__ = ["environment", "create_default_environment", "get_template_dirs"]
