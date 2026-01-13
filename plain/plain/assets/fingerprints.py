import hashlib
import json
from functools import cache

from plain.internal import internalcode
from plain.runtime import PLAIN_TEMP_PATH

_FINGERPRINT_LENGTH = 7


@internalcode
class AssetsFingerprintsManifest(dict):
    """
    A manifest of original filenames to fingerprinted filenames.
    """

    def __init__(self):
        self.path = PLAIN_TEMP_PATH / "assets" / "fingerprints.json"

    def load(self) -> None:
        if self.path.exists():
            with open(self.path) as f:
                self.update(json.load(f))

    def save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self, f, indent=2)


@cache
def _get_manifest() -> AssetsFingerprintsManifest:
    """
    A cached function for loading the asset fingerprints manifest,
    so we don't have to keep loading it from disk over and over.
    """
    manifest = AssetsFingerprintsManifest()
    manifest.load()
    return manifest


def get_fingerprinted_url_path(url_path: str) -> str | None:
    """
    Get the final fingerprinted path for an asset URL path.
    """
    manifest = _get_manifest()
    if url_path in manifest:
        return manifest[url_path]
    return None


def _get_file_fingerprint(file_path: str) -> str:
    """
    Get the fingerprint hash for a file.
    """
    with open(file_path, "rb") as f:
        content = f.read()
        fingerprint_hash = hashlib.md5(content, usedforsecurity=False).hexdigest()[
            :_FINGERPRINT_LENGTH
        ]

    return fingerprint_hash
