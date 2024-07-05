import importlib
from pathlib import Path

from plain.packages import PackageConfig
from plain.runtime import settings


class Config(PackageConfig):
    name = "plain.dev"

    def ready(self):
        # Symlink the plain package into .plain so we can look at it easily
        plain_path = Path(
            importlib.util.find_spec("plain.runtime").origin
        ).parent.parent
        if not settings.PLAIN_TEMP_PATH.exists():
            settings.PLAIN_TEMP_PATH.mkdir()
        src_path = settings.PLAIN_TEMP_PATH / "src"
        if plain_path.exists() and not src_path.exists():
            src_path.symlink_to(plain_path)
