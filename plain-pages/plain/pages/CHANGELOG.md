# plain-pages changelog

## [0.12.1](https://github.com/dropseed/plain/releases/plain-pages@0.12.1) (2025-08-15)

### What's changed

- Improved relative markdown link conversion to handle links that don't use `./` or `../` prefixes, automatically converting plain filenames and paths to proper page URLs ([f98416e](https://github.com/dropseed/plain/commit/f98416e1e7))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-pages@0.12.0) (2025-08-15)

### What's changed

- Redirect pages now use a `status_code` variable instead of the boolean `temporary` variable for greater control over redirect status codes ([ba79ce3](https://github.com/dropseed/plain/commit/ba79ce3d70))
- Removed dependency on `ResponsePermanentRedirect` in favor of using `status_code` parameter in `ResponseRedirect` ([d5735ea](https://github.com/dropseed/plain/commit/d5735ea4f8))

### Upgrade instructions

- Replace any `temporary: false` variables in redirect pages with `status_code: 301` for permanent redirects
- Replace any `temporary: true` variables in redirect pages with `status_code: 302` for temporary redirects (or simply remove the variable as 302 is now the default)

## [0.11.0](https://github.com/dropseed/plain/releases/plain-pages@0.11.0) (2025-08-15)

### What's changed

- Added raw markdown serving feature that allows markdown files to be served at `.md` URLs alongside rendered HTML pages ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))
- Automatic markdown relative link conversion that resolves `./` and `../` links in markdown to proper page URLs ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))
- Added `get_markdown_url()` method to pages for linking to raw markdown content ([b13a544](https://github.com/dropseed/plain/commit/b13a544679c5ffc172fb3e0ef53b97a2a6c50ccb))

### Upgrade instructions

- No changes required

## [0.10.5](https://github.com/dropseed/plain/releases/plain-pages@0.10.5) (2025-07-31)

### What's changed

- Support for symlinks when discovering pages in templates/pages directories ([c5e610d](https://github.com/dropseed/plain/commit/c5e610dfb7161551efdc82a23dac985e89078059))
- Updated package description and comprehensive README documentation ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.10.4](https://github.com/dropseed/plain/releases/plain-pages@0.10.4) (2025-06-23)

### What's changed

- No user-facing changes. This release only updates internal project metadata and documentation.

### Upgrade instructions

- No changes required.
