from bolt.apps import AppConfig
from bolt.staticfiles.checks import check_finders
from bolt import checks


class StaticFilesConfig(AppConfig):
    name = "bolt.staticfiles"
    verbose_name = "Static Files"
    ignore_patterns = ["CVS", ".*", "*~"]

    def ready(self):
        checks.register(check_finders, checks.Tags.staticfiles)
