import importlib
import os

from bolt.packages import PackageConfig
from bolt.runtime import settings


class Config(PackageConfig):
    name = "bolt.dev"

    def ready(self):
        # Symlink the bolt package into .bolt so we can look at it easily
        bolt_path = os.path.dirname(
            os.path.dirname(importlib.util.find_spec("bolt.runtime").origin)
        )
        src_path = settings.BOLT_TEMP_PATH / "src"
        if not src_path.exists():
            src_path.symlink_to(bolt_path)
