"""
Biome standalone binary management for plain-code.
"""

import os
import platform
import subprocess

import requests
import tomlkit

from plain.internal import internalcode
from plain.runtime import PLAIN_TEMP_PATH


@internalcode
class Biome:
    """Download, install, and invoke the Biome CLI standalone binary."""

    @property
    def target_directory(self) -> str:
        # Directory under .plain to store the binary and lockfile
        return str(PLAIN_TEMP_PATH)

    @property
    def standalone_path(self) -> str:
        # On Windows, use .exe suffix
        exe = ".exe" if platform.system() == "Windows" else ""
        return os.path.join(self.target_directory, f"biome{exe}")

    @property
    def version_lockfile_path(self) -> str:
        return os.path.join(self.target_directory, "biome.version")

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

    def get_version_from_config(self) -> str:
        # Read version from pyproject.toml under tool.plain.code.biome
        project_root = os.path.dirname(self.target_directory)
        pyproject = os.path.join(project_root, "pyproject.toml")
        if not os.path.exists(pyproject):
            return ""
        doc = tomlkit.loads(open(pyproject, "rb").read().decode())
        return (
            doc.get("tool", {})
            .get("plain", {})
            .get("code", {})
            .get("biome", {})
            .get("version", "")
        )

    def set_version_in_config(self, version: str) -> None:
        # Persist version to pyproject.toml under tool.plain.code.biome
        project_root = os.path.dirname(self.target_directory)
        pyproject = os.path.join(project_root, "pyproject.toml")
        if not os.path.exists(pyproject):
            return
        doc = tomlkit.loads(open(pyproject, "rb").read().decode())
        doc.setdefault("tool", {}).setdefault("plain", {}).setdefault(
            "code", {}
        ).setdefault("biome", {})["version"] = version
        open(pyproject, "w").write(tomlkit.dumps(doc))

    def detect_platform_slug(self) -> str:
        # Determine the asset slug for the current OS/arch
        system = platform.system()
        arch = platform.machine()
        if system == "Windows":
            # use win32 glibc build
            return "win32-arm64.exe" if arch.lower() == "arm64" else "win32-x64.exe"
        if system == "Linux":
            # prefer glibc builds
            return "linux-arm64" if arch == "aarch64" else "linux-x64"
        if system == "Darwin":
            return "darwin-arm64" if arch == "arm64" else "darwin-x64"
        raise RuntimeError(f"Unsupported platform for Biome: {system}/{arch}")

    def download(self, version: str = "") -> str:
        # Build download URL based on version (tag: cli/vX.Y.Z) or latest
        slug = self.detect_platform_slug()
        if version:
            tag = version if version.startswith("v") else f"v{version}"
            release = f"cli/{tag}"
            url = (
                f"https://github.com/biomejs/biome/releases/download/{release}/"
                f"biome-{slug}"
            )
        else:
            url = (
                f"https://github.com/biomejs/biome/releases/latest/download/"
                f"biome-{slug}"
            )
        resp = requests.get(url, stream=True)
        resp.raise_for_status()
        with open(self.standalone_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        os.chmod(self.standalone_path, 0o755)

        # Determine resolved version for lockfile
        if version:
            resolved = version.lstrip("v")
        else:
            resolved = ""
            if resp.history:
                # Look for redirect to tag cli/vX.Y.Z
                loc = resp.history[0].headers.get("Location", "")
                parts = loc.split("/")
                if "cli" in parts:
                    idx = parts.index("cli")
                    resolved = parts[idx + 1].lstrip("v")

            if not resolved:
                raise RuntimeError("Failed to determine resolved version from redirect")

        open(self.version_lockfile_path, "w").write(resolved)

        return resolved

    def install(self, version: str = "") -> str:
        v = self.download(version)
        self.set_version_in_config(v)
        return v

    def invoke(self, *args, cwd=None) -> subprocess.CompletedProcess:
        # Run the standalone biome binary with given args
        config_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "biome_defaults.json")
        )
        args = list(args) + ["--config-path", config_path, "--vcs-root", os.getcwd()]
        return subprocess.run([self.standalone_path, *args], cwd=cwd)
