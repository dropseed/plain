"""Change-detector tests for AssetsManifest's already-hashed third state.

The user-visible contract (immutable survives compile → reload) lives in
public/test_build_outputs.py; these pin the manifest method in isolation.
"""

from __future__ import annotations

from plain.assets.manifest import AssetsManifest


class TestAlreadyHashedManifest:
    """The manifest's third state: terminal AND fingerprinted (immutable), no redirect."""

    def test_already_hashed_is_immutable(self):
        m = AssetsManifest()
        m.add_already_hashed("dist/app-A1B2C3.js")
        assert m.is_immutable("dist/app-A1B2C3.js") is True

    def test_already_hashed_resolves_to_itself(self):
        m = AssetsManifest()
        m.add_already_hashed("dist/app-A1B2C3.js")
        assert m.resolve("dist/app-A1B2C3.js") == "dist/app-A1B2C3.js"
