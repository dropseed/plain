from django.conf import settings
from django.utils.module_loading import import_string
from .default import create_default_environment
from django.utils.functional import LazyObject


class JinjaEnvironment(LazyObject):
    def _setup(self):
        environment_setting = getattr(settings, "JINJA_ENVIRONMENT", create_default_environment)

        if isinstance(environment_setting, str):
            environment = import_string(environment_setting)()
        else:
            environment = environment_setting()

        self._wrapped = environment


environment = JinjaEnvironment()

__all__ = ["environment", "create_default_environment"]
