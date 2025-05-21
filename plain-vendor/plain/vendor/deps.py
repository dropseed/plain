import re

import requests
import tomlkit

from plain.assets.finders import APP_ASSETS_DIR

from .exceptions import (
    UnknownContentTypeError,
    VersionMismatchError,
)

VENDOR_DIR = APP_ASSETS_DIR / "vendor"


def iter_next_version(version):
    if len(version.split(".")) == 2:
        major, minor = version.split(".")
        yield f"{int(major) + 1}.0"
        yield f"{major}.{int(minor) + 1}"
    elif len(version.split(".")) == 3:
        major, minor, patch = version.split(".")
        yield f"{int(major) + 1}.0.0"
        yield f"{major}.{int(minor) + 1}.0"
        yield f"{major}.{minor}.{int(patch) + 1}"
    else:
        raise ValueError(f"Unable to iterate next version for {version}")


class Dependency:
    def __init__(self, name, **config):
        self.name = name
        self.url = config.get("url", "")
        self.installed = config.get("installed", "")
        self.filename = config.get("filename", "")
        self.sourcemap = config.get("sourcemap", "")

    @staticmethod
    def parse_version_from_url(url):
        if match := re.search(r"\d+\.\d+\.\d+", url):
            return match.group(0)

        if match := re.search(r"\d+\.\d+", url):
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
        if content_type.lower() not in (
            "application/javascript; charset=utf-8",
            "text/javascript; charset=utf-8",
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
                # Try the next few versions
                for v in iter_next_version(self.installed):
                    version, response = try_version(v)
                    if version:
                        break

                    # TODO ideally this would keep going -- if we move to 2.0, and no 3.0, try 2.1, 2.2, etc.

        if not version:
            # Use the currently installed version if we found nothing else
            version, response = self.download(self.installed)

        vendored_path = self.vendor(response)
        self.installed = version

        if self.installed:
            # If the exact version was in the string, replace it with {version} placeholder
            self.url = self.url.replace(self.installed, "{version}")

        self.save_config()
        return vendored_path

    def save_config(self):
        with open("pyproject.toml") as f:
            pyproject = tomlkit.load(f)

        # Force [tool.plain.vendor.dependencies] to be a table
        dependencies = tomlkit.table()
        dependencies.update(
            pyproject.get("tool", {})
            .get("plain", {})
            .get("vendor", {})
            .get("dependencies", {})
        )

        # Force [tool.plain.vendor.dependencies.{name}] to be an inline table
        # name = { url = "https://example.com", installed = "1.0.0" }
        dependencies[self.name] = tomlkit.inline_table()
        dependencies[self.name]["url"] = self.url
        dependencies[self.name]["installed"] = self.installed
        if self.filename:
            dependencies[self.name]["filename"] = self.filename
        if self.sourcemap:
            dependencies[self.name]["sourcemap"] = self.sourcemap

        # Have to give it the right structure in case they don't exist
        if "tool" not in pyproject:
            pyproject["tool"] = tomlkit.table()
        if "plain" not in pyproject["tool"]:
            pyproject["tool"]["plain"] = tomlkit.table()
        if "vendor" not in pyproject["tool"]["plain"]:
            pyproject["tool"]["plain"]["vendor"] = tomlkit.table()

        pyproject["tool"]["plain"]["vendor"]["dependencies"] = dependencies

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
            # Remove any query string or fragment
            filename = filename.split("?")[0].split("#")[0]

        vendored_path = VENDOR_DIR / filename

        with open(vendored_path, "wb") as f:
            f.write(response.content)

        # If a sourcemap is requested, download it as well
        if self.sourcemap:
            if isinstance(self.sourcemap, str):
                # Use a specific filename from config
                sourcemap_filename = self.sourcemap
            else:
                # Otherwise, append .map to the URL
                sourcemap_filename = f"{filename}.map"

            sourcemap_url = "/".join(
                response.url.split("/")[:-1] + [sourcemap_filename]
            )
            sourcemap_response = requests.get(sourcemap_url)
            sourcemap_response.raise_for_status()

            sourcemap_path = VENDOR_DIR / sourcemap_filename

            with open(sourcemap_path, "wb") as f:
                f.write(sourcemap_response.content)

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
