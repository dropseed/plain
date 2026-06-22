# plain-assets changelog

## [0.4.0](https://github.com/dropseed/plain/releases/plain-assets@0.4.0) (2026-06-22)

### What's changed

- Reserved two top-level subdirectory names inside any assets dir for build tooling. A top-level `src/` holds build _inputs_ (a bundler's entry points and the modules they import) — it's skipped by discovery and never served. A top-level `dist/` holds build _outputs_ the tool has already content-hashed — Plain serves them immutable and as-is, without re-fingerprinting (it trusts the build tool's hash). Only the top-level `src/`/`dist/` are special; a nested `foo/src/` is treated normally. Added the `is_build_output()` helper. ([ceefa283](https://github.com/dropseed/plain/commit/ceefa283))
- The assets manifest now records each asset's role inline (redirect target, immutable terminal, or mutable terminal) so immutability survives save/load. ([ceefa283](https://github.com/dropseed/plain/commit/ceefa283))

### Upgrade instructions

- If you serve files from a top-level `src/` directory inside your assets, they will no longer be served — move them out of `src/` (or rename the directory). If you output a build tool's pre-hashed files into a top-level `dist/`, they'll now be served immutable without Plain re-fingerprinting them. Otherwise no changes required.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-assets@0.3.0) (2026-05-12)

### What's changed

- **Command renamed: `plain assets build` → `plain assets compile`.** Now that the command lives under `plain.assets` (not core deploy-prep), the verb follows what the asset pipeline actually does. Pre-steps (user shell commands, package entry points) generate inputs that get compiled. ([3b30b62309](https://github.com/dropseed/plain/commit/3b30b62309))
- **User shell commands move from `[tool.plain.assets.build.run]` to `[tool.plain.assets.run]`.** Drops the redundant `.build.` segment.
- **Entry-point group renamed from `plain.assets.build` to `plain.assets.compile`.** Packages registering pre-compile hooks update their group name.

### Upgrade instructions

- Replace `plain assets build` with `plain assets compile` in deploy scripts, Procfiles, and CI.
- Rename `[tool.plain.assets.build.run]` → `[tool.plain.assets.run]` in your `pyproject.toml`.
- If you ship a third-party package with a build entry point, rename the group from `plain.assets.build` to `plain.assets.compile`. Framework-internal packages (`plain.tailwind`, `plain.esbuild`) are updated in this release wave.

## [0.2.0](https://github.com/dropseed/plain/releases/plain-assets@0.2.0) (2026-05-12)

### What's changed

- **Build orchestrator namespace renamed from `plain.build` to `plain.assets.build`** so the contract follows the package that owns it. ([f698ec3436](https://github.com/dropseed/plain/commit/f698ec3436))
    - User-defined commands move from `[tool.plain.build.run]` to `[tool.plain.assets.build.run]` in `pyproject.toml`.
    - Package entry points move from `[project.entry-points."plain.build"]` to `[project.entry-points."plain.assets.build"]`.
- README documents the build hooks (`[tool.plain.assets.build.run]` for shell commands, the entry-point group for packages) under a new "Pre-compile build steps" section.

### Upgrade instructions

- Rename your `pyproject.toml`:

    ```toml
    # Before
    [tool.plain.build.run]
    openapi = {cmd = "..."}

    # After
    [tool.plain.assets.build.run]
    openapi = {cmd = "..."}
    ```

- If you ship a third-party package that registers a build entry point, rename your entry-point group from `plain.build` to `plain.assets.build`. The framework-internal packages (`plain.tailwind`, `plain.esbuild`) are updated in this release wave.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-assets@0.1.0) (2026-05-12)

### What's changed

- First release. `plain.assets` is now a separate package, extracted from `plain` core ([844f46e428](https://github.com/dropseed/plain/commit/844f46e428)). It owns:
    - The asset finder, manifest, compile pipeline, `AssetView`, and `AssetsRouter`
    - The `plain assets build` CLI command (replaces the old `plain build`)
    - The `asset()` template global
    - Settings: `ASSETS_REDIRECT_ORIGINAL`, `ASSETS_CDN_URL`, `ASSETS_LOG_304`

### Upgrade instructions

- Install the package and add it to `INSTALLED_PACKAGES` — see the [`plain` 0.142.0 release notes](../../../plain/plain/CHANGELOG.md) for the full migration.
