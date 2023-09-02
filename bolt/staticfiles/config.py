from bolt import checks
from bolt.packages import PackageConfig
from bolt.staticfiles.checks import check_finders


class StaticFilesConfig(PackageConfig):
    name = "bolt.staticfiles"
    verbose_name = "Static Files"
    ignore_patterns = ["CVS", ".*", "*~"]

    def ready(self):
        checks.register(check_finders, checks.Tags.staticfiles)
