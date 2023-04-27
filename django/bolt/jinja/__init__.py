from .settings import JINJA_ENVIRONMENT
from django.utils.module_loading import import_string
from .default import create_default_environment


env = (
    import_string(JINJA_ENVIRONMENT)()
    if isinstance(JINJA_ENVIRONMENT, str)
    else JINJA_ENVIRONMENT()
)


__all__ = ["env", "create_default_environment"]
