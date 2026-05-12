# plain-assets changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-assets@0.1.0) (2026-05-12)

### What's changed

- First release. `plain.assets` is now a separate package, extracted from `plain` core ([844f46e428](https://github.com/dropseed/plain/commit/844f46e428)). It owns:
    - The asset finder, manifest, compile pipeline, `AssetView`, and `AssetsRouter`
    - The `plain assets build` CLI command (replaces the old `plain build`)
    - The `asset()` template global
    - Settings: `ASSETS_REDIRECT_ORIGINAL`, `ASSETS_CDN_URL`, `ASSETS_LOG_304`

### Upgrade instructions

- Install the package and add it to `INSTALLED_PACKAGES` — see the [`plain` 0.142.0 release notes](../../../plain/plain/CHANGELOG.md) for the full migration.
