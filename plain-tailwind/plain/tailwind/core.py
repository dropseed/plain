from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
import requests
import tomlkit

from plain.internal import internalcode
from plain.packages import packages_registry
from plain.runtime import APP_PATH, PLAIN_TEMP_PATH, settings


@internalcode
class Tailwind:
    @property
    def target_directory(self) -> str:
        return str(PLAIN_TEMP_PATH)

    @property
    def standalone_path(self) -> str:
        return os.path.join(self.target_directory, "tailwind")

    @property
    def version_lockfile_path(self) -> str:
        return os.path.join(self.target_directory, "tailwind.version")

    @property
    def src_css_path(self) -> Path:
        return settings.TAILWIND_SRC_PATH

    @property
    def dist_css_path(self) -> Path:
        return settings.TAILWIND_DIST_PATH

    def update_plain_sources(self) -> None:
        paths = set()

        # Add paths from installed packages
        for package_config in packages_registry.get_package_configs():
            abs_package_path = os.path.abspath(package_config.path)
            abs_app_path = os.path.abspath(APP_PATH)
            if os.path.commonpath([abs_app_path, abs_package_path]) != abs_app_path:
                paths.add(os.path.relpath(abs_package_path, self.target_directory))

        # Sort the paths so that the order is consistent
        paths = sorted(paths)

        plain_sources_path = os.path.join(self.target_directory, "tailwind.css")
        with open(plain_sources_path, "w") as f:
            for path in paths:
                f.write(f'@source "{path}";\n')

    def invoke(self, *args: Any, cwd: str | None = None) -> None:
        result = subprocess.run([self.standalone_path] + list(args), cwd=cwd)
        if result.returncode != 0:
            sys.exit(result.returncode)

    def is_installed(self) -> bool:
        if not os.path.exists(self.target_directory):
            os.mkdir(self.target_directory)
        return os.path.exists(os.path.join(self.target_directory, "tailwind"))

    def create_src_css(self) -> None:
        os.makedirs(os.path.dirname(self.src_css_path), exist_ok=True)
        with open(self.src_css_path, "w") as f:
            f.write("""@import "tailwindcss";\n@import "./.plain/tailwind.css";\n""")

    def needs_update(self) -> bool:
        locked_version = self.get_installed_version()
        if not locked_version:
            return True

        if locked_version != self.get_version_from_config():
            return True

        return False

    def get_installed_version(self) -> str:
        """Get the currently installed Tailwind version"""
        if not os.path.exists(self.version_lockfile_path):
            return ""

        with open(self.version_lockfile_path) as f:
            return f.read().strip()

    def get_version_from_config(self) -> str:
        pyproject_path = os.path.join(
            os.path.dirname(self.target_directory), "pyproject.toml"
        )

        if not os.path.exists(pyproject_path):
            return ""

        with open(pyproject_path) as f:
            config = tomlkit.load(f)
            return (
                config.get("tool", {})
                .get("plain", {})
                .get("tailwind", {})
                .get("version", "")
            )

    def set_version_in_config(self, version: str) -> None:
        pyproject_path = os.path.join(
            os.path.dirname(self.target_directory), "pyproject.toml"
        )

        with open(pyproject_path) as f:
            config = tomlkit.load(f)

        config.setdefault("tool", {}).setdefault("plain", {}).setdefault(
            "tailwind", {}
        )["version"] = version

        with open(pyproject_path, "w") as f:
            tomlkit.dump(config, f)

    def download(self, version: str = "") -> str:
        if version:
            if not version.startswith("v"):
                version = f"v{version}"
            url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{version}/tailwindcss-{self.detect_platform_slug()}"
        else:
            url = f"https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-{self.detect_platform_slug()}"

        # Optimized requests session with better connection pooling and headers
        session = requests.Session()

        # Better connection pooling
        adapter = requests.adapters.HTTPAdapter(  # type: ignore[attr-defined]
            pool_connections=1, pool_maxsize=10, max_retries=3, pool_block=True
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Optimized headers for better performance
        headers = {
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "User-Agent": "plain-tailwind/1.0",
        }

        with session.get(url, stream=True, headers=headers, timeout=300) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))

            with open(self.standalone_path, "wb") as f:
                with click.progressbar(
                    length=total,
                    label="Downloading Tailwind",
                    width=0,
                ) as bar:
                    # Use 8MB chunks for maximum performance
                    for chunk in response.iter_content(
                        chunk_size=1024 * 1024, decode_unicode=False
                    ):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))

        os.chmod(self.standalone_path, 0o755)

        if not version:
            # Get the version from the redirect chain (latest -> vX.Y.Z)
            version = response.history[1].url.split("/")[-2]

        version = version.lstrip("v")

        with open(self.version_lockfile_path, "w") as f:
            f.write(version)

        return version

    def install(self, version: str = "") -> str:
        installed_version = self.download(version)
        self.set_version_in_config(installed_version)
        return installed_version

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
