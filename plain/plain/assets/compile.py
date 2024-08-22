import gzip
import hashlib
import os
import shutil

from plain.runtime import settings

from .finders import find_assets
from .fingerprints import AssetsFingerprintsManifest

FINGERPRINT_LENGTH = 7

SKIP_COMPRESS_EXTENSIONS = (
    # Images
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",
    # Compressed files
    "zip",
    "gz",
    "tgz",
    "bz2",
    "tbz",
    "xz",
    "br",
    # Fonts
    "woff",
    "woff2",
    # Video
    "3gp",
    "3gpp",
    "asf",
    "avi",
    "m4v",
    "mov",
    "mp4",
    "mpeg",
    "mpg",
    "webm",
    "wmv",
)


def get_compiled_path():
    """
    Get the path at runtime to the compiled assets directory.
    There's no reason currently for this to be a user-facing setting.
    """
    return settings.PLAIN_TEMP_PATH / "assets" / "compiled"


def compile_assets(*, target_dir, keep_original, fingerprint, compress):
    manifest = AssetsFingerprintsManifest()

    for url_path, asset in find_assets().items():
        resolved_path, compiled_paths = compile_asset(
            asset=asset,
            target_dir=target_dir,
            keep_original=keep_original,
            fingerprint=fingerprint,
            compress=compress,
        )
        if resolved_path != url_path:
            manifest[url_path] = resolved_path

        yield url_path, resolved_path, compiled_paths

    if manifest:
        manifest.save()


def compile_asset(*, asset, target_dir, keep_original, fingerprint, compress):
    """
    Compile an asset to multiple output paths.
    """
    compiled_paths = []

    # The expected destination for the original asset
    target_path = os.path.join(target_dir, asset.url_path)

    # Keep track of where the final, resolved asset ends up
    resolved_url_path = asset.url_path

    # Make sure all the expected directories exist
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    base, extension = os.path.splitext(asset.url_path)

    # First, copy the original asset over
    if keep_original:
        shutil.copy(asset.absolute_path, target_path)
        compiled_paths.append(target_path)

    if fingerprint:
        # Fingerprint it with an md5 hash
        # (maybe need a setting with fnmatch patterns for files to NOT fingerprint?
        # that would allow pre-fingerprinted files to be used as-is, and keep source maps etc in tact)
        with open(asset.absolute_path, "rb") as f:
            content = f.read()
            fingerprint_hash = hashlib.md5(content, usedforsecurity=False).hexdigest()[
                :FINGERPRINT_LENGTH
            ]

        fingerprinted_basename = f"{base}.{fingerprint_hash}{extension}"
        fingerprinted_path = os.path.join(target_dir, fingerprinted_basename)
        shutil.copy(asset.absolute_path, fingerprinted_path)
        compiled_paths.append(fingerprinted_path)

        resolved_url_path = os.path.relpath(fingerprinted_path, target_dir)

    if compress and extension not in SKIP_COMPRESS_EXTENSIONS:
        for path in compiled_paths.copy():
            gzip_path = f"{path}.gz"
            with gzip.GzipFile(gzip_path, "wb") as f:
                with open(path, "rb") as f2:
                    f.write(f2.read())
            compiled_paths.append(gzip_path)

    return resolved_url_path, compiled_paths