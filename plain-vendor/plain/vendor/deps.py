import re

import requests
import tomlkit

from plain.assets.finders import APP_ASSETS_DIR

from .exceptions import (
    UnknownContentTypeError,
    VersionMismatchError,
)

VENDOR_DIR = APP_ASSETS_DIR / "vendor"


class Dependency:
    def __init__(self, name, **config):
        self.name = name
        self.url = config.get("url", "")
        self.installed = config.get("installed", "")
        self.filename = config.get("filename", "")

    @staticmethod
    def parse_version_from_url(url):
        match = re.search(r"\d+\.\d+\.\d+", url)
        if match:
            return match.group(0)
        return ""

    def __str__(self):
        return f"{self.name} -> {self.url}"

    def download(self, version):
        # If the string contains a {version} placeholder, replace it
        download_url = self.url.replace("{version}", version)

        response = requests.get(download_url)
        response.raise_for_status()

        content_type = response.headers.get("content-type")
        if content_type not in (
            "application/javascript; charset=utf-8",
            "application/json; charset=utf-8",
            "text/css; charset=utf-8",
        ):
            raise UnknownContentTypeError(
                f"Unknown content type for {self.name}: {content_type}"
            )

        # Good chance it will redirect to a more final URL (which we hope is versioned)
        url = response.url
        version = self.parse_version_from_url(url)

        return version, response

    def install(self):
        if self.installed:
            version, response = self.download(self.installed)
            if version != self.installed:
                raise VersionMismatchError(
                    f"Version mismatch for {self.name}: {self.installed} != {version}"
                )
            return self.vendor(response)
        else:
            return self.update()

    def update(self):
        def try_version(v):
            try:
                version, response = self.download(v)
                return version, response
            except requests.RequestException:
                return "", None

        if not self.installed:
            # If we don't know the installed version yet,
            # just use the url as given
            version, response = self.download("")
        else:
            version, response = try_version("latest")  # A lot of CDNs support this
            if not version:
                # Try bumping semver major version
                current_major = self.installed.split(".")[0]
                version, response = try_version(f"{int(current_major) + 1}.0.0")
            if not version:
                # Try bumping semver minor version
                current_minor = self.installed.split(".")[1]
                version, response = try_version(
                    f"{current_major}.{int(current_minor) + 1}.0"
                )
            if not version:
                # Try bumping semver patch version
                current_patch = self.installed.split(".")[2]
                version, response = try_version(
                    f"{current_major}.{current_minor}.{int(current_patch) + 1}"
                )

        if not version:
            # Use the currently installed version if we found nothing else
            version, response = self.download(self.installed)

        vendored_path = self.vendor(response)
        self.installed = version
        # If the exact version was in the string, replace it with {version} placeholder
        self.url = self.url.replace(self.installed, "{version}")
        self.save_config()
        return vendored_path

    def save_config(self):
        with open("pyproject.toml") as f:
            pyproject = tomlkit.load(f)

        pyproject["tool"]["plain"]["vendor"]["deps"][self.name] = {
            "url": self.url,
            "installed": self.installed,
        }

        with open("pyproject.toml", "w") as f:
            f.write(tomlkit.dumps(pyproject))

    def vendor(self, response):
        if not VENDOR_DIR.exists():
            VENDOR_DIR.mkdir(parents=True)

        if self.filename:
            # Use a specific filename from config
            filename = self.filename
        else:
            # Otherwise, use the filename from the URL
            filename = response.url.split("/")[-1]

        vendored_path = VENDOR_DIR / filename

        with open(vendored_path, "wb") as f:
            f.write(response.content)

        return vendored_path


def get_deps():
    with open("pyproject.toml") as f:
        pyproject = tomlkit.load(f)

    config = (
        pyproject.get("tool", {})
        .get("plain", {})
        .get("vendor", {})
        .get("dependencies", {})
    )

    deps = []

    for name, data in config.items():
        deps.append(Dependency(name, **data))

    return deps
