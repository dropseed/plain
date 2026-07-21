"""Contract for the src/dist build-output roles — the whole assets-side surface.

No build tool is involved — these are hand-placed fixtures exercising
`plain.assets`' two generic rules (any bundler, or none):

- `app/assets/src/`  → build inputs: **skipped by discovery, never served.**
  The whole dir is pruned regardless of contents — the leak fix.
- `app/assets/dist/` → build output, **already content-hashed**: served
  immutable WITHOUT Plain re-md5'ing it (still compressed). The dir is the
  signal. Forward requirement: whatever writes to `dist/` must hash its output
  (an unhashed file served immutable would cache-poison).
- everything else    → static passthrough: md5-fingerprinted as today.

Both rules are inert for existing apps (no top-level src//dist/ today).
"""

from __future__ import annotations

import pytest

from plain.assets import finders
from plain.assets.compile import compile_assets
from plain.assets.manifest import AssetsManifest
from plain.assets.views import AssetView
from plain.runtime import PLAIN_TEMP_PATH
from plain.test import RequestFactory


@pytest.fixture
def assets_tree(tmp_path, monkeypatch):
    """A fixture tree: a src/ input, an already-hashed dist/ output, a static file."""
    root = tmp_path / "assets"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.js").write_text("// build input (entry)")
    (root / "src" / "helper.js").write_text("// build input (imported partial)")
    (root / "dist").mkdir()
    (root / "dist" / "app-A1B2C3.js").write_text("console.log(1)")  # content-hashed
    (root / "css").mkdir()
    (root / "css" / "app.css").write_text("body{}")

    monkeypatch.setattr(finders, "_APP_ASSETS_DIR", root)
    # compile_assets saves the manifest under PLAIN_TEMP_PATH/assets/
    (PLAIN_TEMP_PATH / "assets").mkdir(parents=True, exist_ok=True)
    return root


def compile_tree(target_dir) -> dict[str, str]:
    """Run a real compile, return {url_path: resolved_url_path}."""
    return {
        url_path: resolved
        for url_path, resolved, _compiled in compile_assets(
            target_dir=str(target_dir),
            keep_original=False,
            fingerprint=True,
            compress=False,
        )
    }


class TestSrcIsNotServed:
    def test_src_is_never_served(self, assets_tree, tmp_path):
        compiled = compile_tree(tmp_path / "out")
        leaked = [p for p in compiled if p.startswith("src/")]
        assert leaked == [], f"src/ holds build inputs and must not be served: {leaked}"

    def test_src_pruned_in_every_asset_dir(self, tmp_path, monkeypatch):
        """Each asset dir (e.g. a package dir + the app dir) prunes its own src/."""
        dir_a = tmp_path / "pkg_assets"
        (dir_a / "src").mkdir(parents=True)
        (dir_a / "src" / "a.js").write_text("// input")
        (dir_a / "keep_a.css").write_text("/* a */")
        dir_b = tmp_path / "app_assets"
        (dir_b / "src").mkdir(parents=True)
        (dir_b / "src" / "b.js").write_text("// input")
        (dir_b / "keep_b.css").write_text("/* b */")
        monkeypatch.setattr(
            finders, "_iter_asset_dirs", lambda: iter([str(dir_a), dir_b])
        )

        served = {asset.url_path for asset in finders._iter_assets()}
        assert not any(p.startswith("src/") for p in served), served
        assert {"keep_a.css", "keep_b.css"} <= served


class TestDistIsAlreadyHashed:
    def test_dist_served_at_its_own_name(self, assets_tree, tmp_path):
        # already content-hashed by the build tool → served as-is, NOT re-md5'd.
        compiled = compile_tree(tmp_path / "out")
        assert compiled.get("dist/app-A1B2C3.js") == "dist/app-A1B2C3.js"


class TestStaticRegressionGuard:
    def test_static_is_still_md5_fingerprinted(self, assets_tree, tmp_path):
        compiled = compile_tree(tmp_path / "out")
        resolved = compiled["css/app.css"]
        assert resolved != "css/app.css"
        assert resolved.startswith("css/app.")
        assert resolved.endswith(".css")


class TestCompileToReload:
    """The full assets-side chain: discover → compile → persist → fresh reload,
    the way production does it (compile writes the manifest, serving reads it)."""

    def test_compiled_dist_is_immutable_after_reload(self, assets_tree, tmp_path):
        compile_tree(tmp_path / "out")  # compile_assets writes manifest.json to disk

        reloaded = AssetsManifest()  # path defaults to where compile just saved it
        reloaded.load()

        assert reloaded.is_immutable("dist/app-A1B2C3.js") is True
        assert reloaded.resolve("dist/app-A1B2C3.js") == "dist/app-A1B2C3.js"
        # the static original is mutable (it redirects to its fingerprinted name)
        assert reloaded.is_immutable("css/app.css") is False
        resolved = reloaded.resolve("css/app.css")
        assert resolved is not None
        assert resolved.startswith("css/app.")


class TestManifestRoundTrip:
    """The immutable contract must survive save → load — production compiles the
    manifest to disk, then AssetView.get_manifest() loads it back to serve."""

    def test_already_hashed_immutable_survives_reload(self, tmp_path):
        saved = AssetsManifest()
        saved.path = tmp_path / "manifest.json"
        saved.add_already_hashed("dist/app-A1B2C3.js")
        saved.add_fingerprinted("css/style.css", "css/style.abc1234.css")
        saved.save()

        loaded = AssetsManifest()
        loaded.path = tmp_path / "manifest.json"
        loaded.load()

        # Both the already-hashed file and a normal fingerprinted target stay immutable.
        assert loaded.is_immutable("dist/app-A1B2C3.js") is True
        assert loaded.is_immutable("css/style.abc1234.css") is True
        assert loaded.resolve("dist/app-A1B2C3.js") == "dist/app-A1B2C3.js"
        assert loaded.resolve("css/style.css") == "css/style.abc1234.css"


class TestDistServedImmutable:
    """Serving side: an already-hashed dist/ file is cached immutable (far-future)."""

    def test_dist_file_is_immutable(self):
        manifest = AssetsManifest()
        manifest.add_already_hashed("dist/app-A1B2C3.js")

        class _View(AssetView):
            def get_manifest(self):
                return manifest

        view = _View(
            request=RequestFactory().get("/assets/dist/app-A1B2C3.js"),
            url_kwargs={"path": "dist/app-A1B2C3.js"},
        )
        assert view.is_immutable("dist/app-A1B2C3.js") is True
