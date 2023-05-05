import subprocess
from pathlib import Path
from django.utils.functional import cached_property

class DevPaths:
    def __init__(self, target: Path | None = None):
        self.target = target
        if not self.target:
            self.target = Path.cwd()

    @cached_property
    def app(self) -> Path:
        if (self.target / "app").exists():
            return self.target / "app"

        return self.target

    @cached_property
    def dot_bolt(self) -> Path:
        if self.repo:
            path = self.repo / ".bolt"
        else:
            path = self.target / ".bolt"

        if not path.exists():
            path.mkdir()

        gitignore_path = path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("# Created by bolt\n*\n")

        return path

    @cached_property
    def repo(self) -> Path | None:
        try:
            root = (
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=self.target,
                    stderr=subprocess.DEVNULL,
                )
                .decode("utf-8")
                .strip()
            )
        except subprocess.CalledProcessError:
            root = None
        return Path(root)


paths = DevPaths()
