"""
Oxc standalone binary management for plain-code.

Downloads and manages oxlint (linter) and oxfmt (formatter) binaries
from the oxc-project/oxc GitHub releases.
"""

from __future__ import annotations

import io
import os
import platform
import subprocess
import tarfile
import zipfile

import click
import requests
import tomlkit

from plain.runtime import PLAIN_TEMP_PATH

TAG_PREFIX = "apps_v"


class OxcTool:
    """Download, install, and invoke an Oxc CLI binary (oxlint or oxfmt)."""

    def __init__(self, name: str) -> None:
        if name not in ("oxlint", "oxfmt"):
            raise ValueError(f"Unknown Oxc tool: {name}")
        self.name = name

    @property
    def target_directory(self) -> str:
        return str(PLAIN_TEMP_PATH)

    @property
    def standalone_path(self) -> str:
        exe = ".exe" if platform.system() == "Windows" else ""
        return os.path.join(self.target_directory, f"{self.name}{exe}")

    @property
    def version_lockfile_path(self) -> str:
        return os.path.join(self.target_directory, "oxc.version")

    def is_installed(self) -> bool:
        td = self.target_directory
        if not os.path.isdir(td):
            os.makedirs(td, exist_ok=True)
        return os.path.exists(self.standalone_path)

    def needs_update(self) -> bool:
        if not self.is_installed():
            return True
        if not os.path.exists(self.version_lockfile_path):
            return True
        with open(self.version_lockfile_path) as f:
            locked = f.read().strip()
        return locked != self.get_version_from_config()

    @staticmethod
    def get_version_from_config() -> str:
        project_root = os.path.dirname(str(PLAIN_TEMP_PATH))
        pyproject = os.path.join(project_root, "pyproject.toml")
        if not os.path.exists(pyproject):
            return ""
        doc = tomlkit.loads(open(pyproject, "rb").read().decode())
        return (
            doc.get("tool", {})
            .get("plain", {})
            .get("code", {})
            .get("oxc", {})
            .get("version", "")
        )

    @staticmethod
    def set_version_in_config(version: str) -> None:
        project_root = os.path.dirname(str(PLAIN_TEMP_PATH))
        pyproject = os.path.join(project_root, "pyproject.toml")
        if not os.path.exists(pyproject):
            return
        doc = tomlkit.loads(open(pyproject, "rb").read().decode())
        doc.setdefault("tool", {}).setdefault("plain", {}).setdefault(
            "code", {}
        ).setdefault("oxc", {})["version"] = version
        open(pyproject, "w").write(tomlkit.dumps(doc))

    def detect_platform_slug(self) -> str:
        system = platform.system()
        arch = platform.machine()
        if system == "Windows":
            if arch.lower() in ("arm64", "aarch64"):
                return "aarch64-pc-windows-msvc"
            return "x86_64-pc-windows-msvc"
        if system == "Linux":
            if arch == "aarch64":
                return "aarch64-unknown-linux-gnu"
            return "x86_64-unknown-linux-gnu"
        if system == "Darwin":
            if arch == "arm64":
                return "aarch64-apple-darwin"
            return "x86_64-apple-darwin"
        raise RuntimeError(f"Unsupported platform for Oxc: {system}/{arch}")

    def download(self, version: str = "") -> str:
        slug = self.detect_platform_slug()
        is_windows = platform.system() == "Windows"
        ext = "zip" if is_windows else "tar.gz"
        asset = f"{self.name}-{slug}.{ext}"

        if version:
            url = f"https://github.com/oxc-project/oxc/releases/download/{TAG_PREFIX}{version}/{asset}"
        else:
            url = f"https://github.com/oxc-project/oxc/releases/latest/download/{asset}"

        resp = requests.get(url, stream=True)
        resp.raise_for_status()

        td = self.target_directory
        if not os.path.isdir(td):
            os.makedirs(td, exist_ok=True)

        # Download into memory for extraction
        data = io.BytesIO()
        total = int(resp.headers.get("Content-Length", 0))
        if total:
            with click.progressbar(
                length=total,
                label=f"Downloading {self.name}",
                width=0,
            ) as bar:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    data.write(chunk)
                    bar.update(len(chunk))
        else:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                data.write(chunk)

        data.seek(0)

        # Extract the binary from the archive
        if is_windows:
            with zipfile.ZipFile(data) as zf:
                # Find the binary inside the archive
                members = zf.namelist()
                binary_name = next(m for m in members if m.startswith(self.name))
                with (
                    zf.open(binary_name) as src,
                    open(self.standalone_path, "wb") as dst,
                ):
                    dst.write(src.read())
        else:
            with tarfile.open(fileobj=data, mode="r:gz") as tf:
                members = tf.getnames()
                binary_name = next(m for m in members if m.startswith(self.name))
                extracted = tf.extractfile(binary_name)
                if extracted is None:
                    raise RuntimeError(f"Failed to extract {binary_name} from archive")
                with open(self.standalone_path, "wb") as dst:
                    dst.write(extracted.read())

        os.chmod(self.standalone_path, 0o755)

        # Determine resolved version for lockfile
        if version:
            resolved = version.lstrip("v")
        else:
            resolved = ""
            if resp.history:
                loc = resp.history[0].headers.get("Location", "")
                if TAG_PREFIX in loc:
                    remaining = loc.split(TAG_PREFIX, 1)[-1]
                    resolved = remaining.split("/")[0]

            if not resolved:
                raise RuntimeError("Failed to determine resolved version from redirect")

        return resolved

    def invoke(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        config_path = os.path.join(
            os.path.dirname(__file__), f"{self.name}_defaults.json"
        )
        extra_args = ["-c", config_path]
        return subprocess.run([self.standalone_path, *extra_args, *args], cwd=cwd)


def install_oxc(version: str = "") -> str:
    """Install both oxlint and oxfmt, return the resolved version."""
    oxlint = OxcTool("oxlint")
    oxfmt = OxcTool("oxfmt")

    resolved = oxlint.download(version)
    oxfmt.download(resolved)

    # Write version lockfile once (shared by both tools)
    with open(oxlint.version_lockfile_path, "w") as f:
        f.write(resolved)

    OxcTool.set_version_in_config(resolved)
    return resolved
