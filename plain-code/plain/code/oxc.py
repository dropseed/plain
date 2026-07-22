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
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import click
import httpx
import tomlkit

from plain.runtime import PLAIN_CACHE_PATH, PLAIN_TEMP_PATH

TAG_PREFIX = "apps_v"

# Paths that should never be linted or formatted. These are passed on the
# command line rather than through a config file: as of oxc 1.75, config-file
# `ignorePatterns` only apply to files underneath the config file's own
# directory, and ours ships inside the installed package.
IGNORE_PATTERNS = [
    "**/vendor/**",
    "**/node_modules/**",
    "**/*.min.*",
    "**/htmlcov/**",
    "**/.venv/**",
    "**/.pytest_cache/**",
]


class OxcTool:
    """Download, install, and invoke an Oxc CLI binary (oxlint or oxfmt)."""

    def __init__(self, name: str) -> None:
        if name not in ("oxlint", "oxfmt"):
            raise ValueError(f"Unknown Oxc tool: {name}")
        self.name = name

    def binary_path(self, version: str) -> Path:
        """Machine-level cache path for a specific Oxc version."""
        exe = ".exe" if platform.system() == "Windows" else ""
        return PLAIN_CACHE_PATH / "oxc" / version / f"{self.name}{exe}"

    def is_installed(self) -> bool:
        version = self.get_version_from_config()
        return bool(version) and self.binary_path(version).exists()

    @staticmethod
    def get_version_from_config() -> str:
        project_root = os.path.dirname(str(PLAIN_TEMP_PATH))
        pyproject = os.path.join(project_root, "pyproject.toml")
        if not os.path.exists(pyproject):
            return ""
        with open(pyproject, "rb") as f:
            doc = tomllib.load(f)
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
        with open(pyproject) as f:
            doc = tomlkit.load(f)
        doc.setdefault("tool", {}).setdefault("plain", {}).setdefault(
            "code", {}
        ).setdefault("oxc", {})["version"] = version
        with open(pyproject, "w") as f:
            tomlkit.dump(doc, f)

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

    @staticmethod
    def get_latest_version() -> str:
        """Find the latest apps_v release tag via the GitHub API."""
        resp = httpx.get(
            "https://api.github.com/repos/oxc-project/oxc/releases",
            params={"per_page": 20},
            headers={"Accept": "application/vnd.github+json"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        for release in resp.json():
            tag = release["tag_name"]
            if tag.startswith(TAG_PREFIX):
                return tag[len(TAG_PREFIX) :]
        raise RuntimeError("No apps_v release found on GitHub")

    def download(self, version: str = "") -> str:
        if not version:
            version = self.get_latest_version()

        slug = self.detect_platform_slug()
        is_windows = platform.system() == "Windows"
        ext = "zip" if is_windows else "tar.gz"
        asset = f"{self.name}-{slug}.{ext}"
        url = f"https://github.com/oxc-project/oxc/releases/download/{TAG_PREFIX}{version}/{asset}"

        # Download into memory for extraction
        data = io.BytesIO()
        with httpx.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            if total:
                with click.progressbar(
                    length=total,
                    label=f"Downloading {self.name}",
                    width=0,
                ) as bar:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        data.write(chunk)
                        bar.update(len(chunk))
            else:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    data.write(chunk)

        data.seek(0)

        # Extract to a temp file first, then atomically move it into the
        # versioned cache path (parallel checkouts can download concurrently).
        resolved = version.lstrip("v")
        binary_path = self.binary_path(resolved)
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = binary_path.parent / f".{self.name}-download-{os.getpid()}"

        try:
            if is_windows:
                with zipfile.ZipFile(data) as zf:
                    # Find the binary inside the archive
                    members = zf.namelist()
                    binary_name = next(m for m in members if m.startswith(self.name))
                    with (
                        zf.open(binary_name) as src,
                        open(tmp_path, "wb") as dst,
                    ):
                        dst.write(src.read())
            else:
                with tarfile.open(fileobj=data, mode="r:gz") as tf:
                    members = tf.getnames()
                    binary_name = next(m for m in members if m.startswith(self.name))
                    extracted = tf.extractfile(binary_name)
                    if extracted is None:
                        raise RuntimeError(
                            f"Failed to extract {binary_name} from archive"
                        )
                    with open(tmp_path, "wb") as dst:
                        dst.write(extracted.read())

            os.chmod(tmp_path, 0o755)
            os.replace(tmp_path, binary_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        return resolved

    def invoke(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        version = self.get_version_from_config()
        if not version:
            raise RuntimeError(
                "No Oxc version configured in pyproject.toml — run `plain code install`"
            )
        if self.name == "oxlint":
            # oxlint takes ignores as repeated --ignore-pattern flags.
            ignore_args = []
            for pattern in IGNORE_PATTERNS:
                ignore_args += ["--ignore-pattern", pattern]
        else:
            # oxfmt has no --ignore-pattern; it excludes via `!`-prefixed paths.
            ignore_args = [f"!{pattern}" for pattern in IGNORE_PATTERNS]
        result = subprocess.run(
            [self.binary_path(version), *args, *ignore_args],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        # oxfmt errors when no matching files are found — treat as success
        if (
            result.returncode != 0
            and "Expected at least one target file" in result.stderr
        ):
            result.returncode = 0
        elif result.stderr:
            # We deliberately don't pass a config file, so drop oxfmt's nudge to
            # add one — projects can still add their own `.oxfmtrc.json`.
            stderr = "".join(
                line
                for line in result.stderr.splitlines(keepends=True)
                if "No config found, using defaults" not in line
            )
            if stderr:
                print(stderr, end="", file=sys.stderr)
        return result


def install_oxc(version: str = "") -> str:
    """Install both oxlint and oxfmt, return the resolved version."""
    oxlint = OxcTool("oxlint")
    oxfmt = OxcTool("oxfmt")

    resolved = oxlint.download(version)
    oxfmt.download(resolved)

    OxcTool.set_version_in_config(resolved)
    return resolved
