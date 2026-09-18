from __future__ import annotations

import hashlib
import json
from functools import cache

from plain.runtime import PLAIN_TEMP_PATH

_FINGERPRINT_LENGTH = 7


class AssetsManifest(dict[str, str | bool]):
    """
    A manifest of compiled assets. Each path's value encodes its role:

    - a ``str`` → redirect to that served URL (an original → its fingerprinted name)
    - ``True``  → an immutable terminal (served at its own name, cache forever)
    - ``False`` → a mutable terminal (served at its own name, short cache)

    Immutability is stored inline, not derived — so it survives save/load, and a
    really large manifest stays compact (one bare flag per terminal, no second
    structure). Paths not in the manifest were not compiled.
    """

    def __init__(self):
        self.path = PLAIN_TEMP_PATH / "assets" / "manifest.json"

    def load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path) as f:
            self.update(json.load(f))

    def save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self, f, indent=2)

    def add_fingerprinted(self, original_path: str, fingerprinted_path: str) -> None:
        """Add a Plain-fingerprinted asset: the original redirects to the immutable hashed name."""
        self[original_path] = fingerprinted_path
        self[fingerprinted_path] = True

    def add_non_fingerprinted(self, path: str) -> None:
        """Add a mutable terminal — served at its own name, not cached forever."""
        self[path] = False

    def add_already_hashed(self, path: str) -> None:
        """Add an already content-hashed asset: an immutable terminal whose hash the
        build tool owns, so Plain serves it as-is (no md5 rename)."""
        self[path] = True

    def is_immutable(self, path: str) -> bool:
        """Whether the path is served with far-future immutable caching."""
        return self.get(path) is True

    def resolve(self, url_path: str) -> str | None:
        """Resolve an asset URL path to its served path.

        Returns the redirect target for an original, the path itself for a
        terminal, or None if the asset was not compiled.
        """
        if url_path not in self:
            return None
        target = self[url_path]
        return target if isinstance(target, str) else url_path


@cache
def get_manifest() -> AssetsManifest:
    """
    A cached function for loading the assets manifest,
    so we don't have to keep loading it from disk over and over.
    """
    manifest = AssetsManifest()
    manifest.load()
    return manifest


def compute_fingerprint(file_path: str) -> str:
    """Compute an MD5-based fingerprint hash for a file."""
    with open(file_path, "rb") as f:
        content = f.read()

    return hashlib.md5(content, usedforsecurity=False).hexdigest()[:_FINGERPRINT_LENGTH]
