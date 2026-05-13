# plain-esbuild changelog

## [0.10.0](https://github.com/dropseed/plain/releases/plain-esbuild@0.10.0) (2026-05-12)

### What's changed

- Entry-point group renamed from `plain.assets.build` to `plain.assets.compile` to match the renamed `plain assets compile` command (see [plain-assets 0.3.0](../../../plain-assets/plain/assets/CHANGELOG.md)). README updated to reference the new command. Pins `plain.assets>=0.3.0`. ([3b30b62309](https://github.com/dropseed/plain/commit/3b30b62309))

### Upgrade instructions

- No changes required if you upgrade `plain.assets` to 0.3.0+ in the same step.

## [0.9.0](https://github.com/dropseed/plain/releases/plain-esbuild@0.9.0) (2026-05-12)

### What's changed

- Entry-point group renamed from `plain.build` to `plain.assets.build` to match the new `plain.assets.build` namespace (see [plain-assets 0.2.0](../../../plain-assets/plain/assets/CHANGELOG.md)). Pins `plain.assets>=0.2.0` since the new group is only iterated by that version. ([f698ec3436](https://github.com/dropseed/plain/commit/f698ec3436))

### Upgrade instructions

- No changes required if you upgrade `plain.assets` to 0.2.0+ in the same step.

## [0.8.3](https://github.com/dropseed/plain/releases/plain-esbuild@0.8.3) (2026-05-12)

### What's changed

- Adds explicit `plain.assets>=0.1.0,<1.0.0` dependency now that `plain.assets` is a separate package (extracted from `plain` core in 0.142.0). README updated to reference `plain assets build` instead of the retired `plain build`. ([844f46e428](https://github.com/dropseed/plain/commit/844f46e428))

### Upgrade instructions

- No changes required if you're upgrading `plain` in the same step — `plain.assets` comes along as a transitive dependency.

## [0.8.2](https://github.com/dropseed/plain/releases/plain-esbuild@0.8.2) (2026-05-05)

### What's changed

- Exposes `__version__` from `importlib.metadata` on `plain.esbuild` for version probes that don't want to scrape pip metadata. ([c6cf6edb](https://github.com/dropseed/plain/commit/c6cf6edb))

### Upgrade instructions

- No changes required.

## [0.8.1](https://github.com/dropseed/plain/releases/plain-esbuild@0.8.1) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.8.0](https://github.com/dropseed/plain/releases/plain-esbuild@0.8.0) (2026-01-13)

### What's changed

- Documentation has been updated with improved structure, examples, and installation instructions ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb8a683c65863f4d0b7af9af5b16feec))

### Upgrade instructions

- No changes required

## [0.7.1](https://github.com/dropseed/plain/releases/plain-esbuild@0.7.1) (2025-10-24)

### What's changed

- The esbuild file watcher now ignores `.tmp.` and `.esbuilt.` files to prevent unnecessary rebuilds ([f60d6be](https://github.com/dropseed/plain/commit/f60d6bee3d52ad5af763a84126de1cd40a85d33f))

### Upgrade instructions

- No changes required

## [0.7.0](https://github.com/dropseed/plain/releases/plain-esbuild@0.7.0) (2025-10-17)

### What's changed

- Removed `watchfiles` dependency - file watching functionality has been moved to `plain-dev` ([cd92e30](https://github.com/dropseed/plain/commit/cd92e302cd77afef999639e4533f118114738015))

### Upgrade instructions

- No changes required

## [0.6.1](https://github.com/dropseed/plain/releases/plain-esbuild@0.6.1) (2025-10-06)

### What's changed

- Added type annotations throughout the package for improved IDE and type checker support ([968193c](https://github.com/dropseed/plain/commit/968193c55af3254b848a6c9ebe9406b3e86efd64))

### Upgrade instructions

- No changes required

## [0.6.0](https://github.com/dropseed/plain/releases/plain-esbuild@0.6.0) (2025-09-19)

### What's changed

- Python 3.13 is now the minimum required version ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb0d5e8f5001efccede4d58d0e26bfea))
- Package description has been added to the pyproject.toml ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))
- README has been updated with proper formatting and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- Upgrade your Python environment to Python 3.13 or newer

## [0.5.1](https://github.com/dropseed/plain/releases/plain-esbuild@0.5.1) (2025-06-24)

### What's changed

- Added this CHANGELOG file to the package so future releases include detailed notes ([82710c3](https://github.com/dropseed/plain/commit/82710c3c8300))

### Upgrade instructions

- No changes required
