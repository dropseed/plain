import functools
from pathlib import Path

from django.conf import settings
from django.utils.functional import cached_property
from django.utils.module_loading import import_string


@functools.lru_cache
def get_default_renderer():
    renderer_class = import_string(settings.FORM_RENDERER)
    return renderer_class()


class BaseRenderer:
    form_template_name = "django/forms/div.html"
    formset_template_name = "django/forms/formsets/div.html"

    def get_template(self, template_name):
        raise NotImplementedError("subclasses must implement get_template()")

    def render(self, template_name, context, request=None):
        template = self.get_template(template_name)
        return template.render(context, request=request).strip()


class EngineMixin:
    def get_template(self, template_name):
        return self.engine.get_template(template_name)

    @cached_property
    def engine(self):
        return self.backend(
            {
                "APP_DIRS": True,
                "DIRS": [Path(__file__).parent / self.backend.app_dirname],
                "NAME": "djangoforms",
                "OPTIONS": {},
            }
        )


class Jinja2(EngineMixin, BaseRenderer):
    """
    Load Jinja2 templates from the built-in widget templates in
    django/forms/jinja2 and from apps' 'jinja2' directory.
    """

    @cached_property
    def backend(self):
        from django.template.backends.jinja2 import Jinja2

        return Jinja2
