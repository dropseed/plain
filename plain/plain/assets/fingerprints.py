import json
from functools import cache

from plain.runtime import settings


class AssetsFingerprintsManifest(dict):
    def __init__(self):
        self.path = settings.PLAIN_TEMP_PATH / "assets" / "fingerprints.json"

    def load(self):
        if self.path.exists():
            with open(self.path) as f:
                self.update(json.load(f))

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self, f, indent=2)


@cache
def _get_manifest():
    """
    A cached function for loading the asset fingerprints manifest,
    so we don't have to keep loading it from disk over and over.
    """
    manifest = AssetsFingerprintsManifest()
    manifest.load()
    return manifest


def get_fingerprinted_url_path(url_path):
    """
    Get the final fingerprinted path for an asset URL path.
    """
    manifest = _get_manifest()
    if url_path in manifest:
        return manifest[url_path]
