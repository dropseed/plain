from django.conf import settings
from .default import get_default_environment


# Should be a path to a callable that returns a jinja2.Environment instance
JINJA_ENVIRONMENT = getattr(settings, "JINJA_ENVIRONMENT", get_default_environment)
