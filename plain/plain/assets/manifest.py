from __future__ import annotations

import hashlib
import json
from functools import cache

from plain.internal import internalcode
from plain.runtime import PLAIN_TEMP_PATH

_FINGERPRINT_LENGTH = 7


@internalcode
class AssetsManifest(dict[str, str | None]):
    """
    A manifest of compiled assets.

    Keys are all compiled asset paths. Values are either:
    - A string path to redirect to (original → fingerprinted)
    - None if this is the final path (no redirect needed)

    Assets not in the manifest were not compiled.
    """

    def __init__(self):
        self.path = PLAIN_TEMP_PATH / "assets" / "manifest.json"
        self.fingerprinted_paths: set[str] = set()

    def load(self) -> None:
        if self.path.exists():
            with open(self.path) as f:
                self.update(json.load(f))
        # Build set of fingerprinted paths (redirect targets from original → fingerprinted mappings)
        self.fingerprinted_paths = {v for v in self.values() if v is not None}

    def save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self, f, indent=2)

    def add_fingerprinted(self, original_path: str, fingerprinted_path: str) -> None:
        """Add a fingerprinted asset.

        Creates two entries:
        - original_path -> fingerprinted_path (redirect)
        - fingerprinted_path -> None (terminal)
        """
        self[original_path] = fingerprinted_path
        self[fingerprinted_path] = None
        self.fingerprinted_paths.add(fingerprinted_path)

    def add_non_fingerprinted(self, path: str) -> None:
        """Add a non-fingerprinted asset (terminal, no redirect)."""
        self[path] = None

    def is_fingerprinted(self, path: str) -> bool:
        """Check if a path is a fingerprinted path (pointed to by another entry)."""
        return path in self.fingerprinted_paths

    def resolve(self, url_path: str) -> str | None:
        """
        Get the best compiled path for an asset URL path.

        Returns the redirect target if one exists, otherwise the path itself if compiled.
        Returns None if the asset is not in the manifest (was not compiled).
        """
        if url_path not in self:
            return None
        # If there's a redirect target, use it; otherwise use the path itself
        return self[url_path] or url_path


@internalcode
@cache
def get_manifest() -> AssetsManifest:
    """
    A cached function for loading the assets manifest,
    so we don't have to keep loading it from disk over and over.
    """
    manifest = AssetsManifest()
    manifest.load()
    return manifest


@internalcode
def compute_fingerprint(file_path: str) -> str:
    """Compute an MD5-based fingerprint hash for a file."""
    with open(file_path, "rb") as f:
        content = f.read()

    return hashlib.md5(content, usedforsecurity=False).hexdigest()[:_FINGERPRINT_LENGTH]
