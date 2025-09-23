# plain-tunnel changelog

## [0.7.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.7.0) (2025-09-22)

### What's changed

- Removed manual ALLOWED_HOSTS configuration documentation from README as it's now handled automatically by the Plain framework ([d3cb771](https://github.com/dropseed/plain/commit/d3cb7712b9))

### Upgrade instructions

- Changed ALLOWED_HOSTS default to `[]` with a deploy-only preflight check to ensure it's set in production environments

## [0.6.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.6.0) (2025-09-19)

### What's changed

- Updated minimum Python version requirement from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Enhanced README documentation with improved structure, table of contents, and detailed usage examples ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Added proper project description to pyproject.toml ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- Update your Python environment to Python 3.13 or higher

## [0.5.5](https://github.com/dropseed/plain/releases/plain-tunnel@0.5.5) (2025-07-07)

### What's changed

- No user-facing changes. Internal code cleanup and Biome linter fixes in the Cloudflare worker implementation ([3265f5f](https://github.com/dropseed/plain/commit/3265f5f), [9327384](https://github.com/dropseed/plain/commit/9327384)).

### Upgrade instructions

- No changes required
