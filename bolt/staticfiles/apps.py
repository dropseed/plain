from bolt.apps import AppConfig
from bolt.staticfiles.checks import check_finders
from django.core import checks
from bolt.utils.translation import gettext_lazy as _


class StaticFilesConfig(AppConfig):
    name = "bolt.staticfiles"
    verbose_name = _("Static Files")
    ignore_patterns = ["CVS", ".*", "*~"]

    def ready(self):
        checks.register(check_finders, checks.Tags.staticfiles)
