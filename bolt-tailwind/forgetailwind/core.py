import os
import platform
import re
import subprocess
import sys

import requests

DEFAULT_CSS = """@tailwind base;


@tailwind components;


@tailwind utilities;
"""


class Tailwind:
    def __init__(self, target_directory, django_directory):
        self.target_directory = target_directory
        self.django_directory = django_directory

    @property
    def standalone_path(self) -> str:
        return os.path.join(self.target_directory, "tailwind")

    @property
    def version_lockfile_path(self) -> str:
        return os.path.join(self.target_directory, "tailwind.version")

    @property
    def config_path(self) -> str:
        return os.path.join(
            os.path.dirname(self.target_directory), "tailwind.config.js"
        )

    @property
    def src_css_path(self) -> str:
        return os.path.join(self.django_directory, "static", "src", "tailwind.css")

    @property
    def dist_css_path(self) -> str:
        return os.path.join(self.django_directory, "static", "dist", "tailwind.css")

    def invoke(self, *args, cwd=None) -> None:
        result = subprocess.run([self.standalone_path] + list(args), cwd=cwd)
        if result.returncode != 0:
            sys.exit(result.returncode)

    def is_installed(self) -> bool:
        return os.path.exists(os.path.join(self.target_directory, "tailwind"))

    def config_exists(self) -> bool:
        return os.path.exists(self.config_path)

    def create_config(self):
        self.invoke("init", self.config_path)

    def src_css_exists(self) -> bool:
        return os.path.exists(self.src_css_path)

    def create_src_css(self):
        os.makedirs(os.path.dirname(self.src_css_path), exist_ok=True)
        with open(self.src_css_path, "w") as f:
            f.write(DEFAULT_CSS)

    def needs_update(self) -> bool:
        if not os.path.exists(self.version_lockfile_path):
            return True

        with open(self.version_lockfile_path) as f:
            locked_version = f.read().strip()

        if locked_version != self.get_version_from_config():
            return True

        return False

    def get_version_from_config(self) -> str:
        if not self.config_exists():
            return ""

        config_contents = open(self.config_path).read()
        matches = re.search(r"const FORGE_TAILWIND_VERSION = \"(.*)\"", config_contents)
        if matches:
            return matches.group(1)

        return ""

    def set_version_in_config(self, version):
        config_contents = open(self.config_path).read()
        if "const FORGE_TAILWIND_VERSION" not in config_contents:
            # prepend it to the file
            config_contents = (
                f'const FORGE_TAILWIND_VERSION = "{version}"\n\n' + config_contents
            )
        else:
            config_contents = re.sub(
                r"const FORGE_TAILWIND_VERSION = \"(.*)\"",
                f'const FORGE_TAILWIND_VERSION = "{version}"',
                config_contents,
            )

        with open(self.config_path, "w") as f:
            f.write(config_contents)

    def install(self, version="") -> str:
        if version:
            if not version.startswith("v"):
                version = f"v{version}"
            url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{version}/tailwindcss-{self.detect_platform_slug()}"
        else:
            url = f"https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-{self.detect_platform_slug()}"

        with requests.get(url, stream=True) as response:
            response.raise_for_status()
            with open(self.standalone_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        os.chmod(self.standalone_path, 0o755)

        if not version:
            # Get the version from the redirect chain (latest -> vX.Y.Z)
            version = response.history[1].url.split("/")[-2].lstrip("v")

        with open(self.version_lockfile_path, "w") as f:
            f.write(version)

        self.set_version_in_config(version)

        return version

    @staticmethod
    def detect_platform_slug() -> str:
        uname = platform.uname()[0]

        if uname == "Windows":
            return "windows-x64.exe"

        if uname == "Linux" and platform.uname()[4] == "aarch64":
            return "linux-arm64"

        if uname == "Linux":
            return "linux-x64"

        if uname == "Darwin" and platform.uname().machine == "arm64":
            return "macos-arm64"

        if uname == "Darwin":
            return "macos-x64"

        raise Exception("Unsupported platform for Tailwind standalone")
