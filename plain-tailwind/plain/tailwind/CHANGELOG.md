# plain-tailwind changelog

## [0.21.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.21.0) (2026-04-30)

### What's changed

- **Auto-import package `tailwind.css` files into the Tailwind build.** If an installed package ships a `tailwind.css` file next to its `__init__.py`, an `@import` for it is automatically added to `.plain/tailwind.css` — no user configuration required. Use it for design tokens (`@theme`), component layers, `@custom-variant`s, or anything else that needs to be part of the Tailwind compilation. `plain-admin` 0.80.0 uses this mechanism to ship its component CSS layer. ([6a49f35a84bd](https://github.com/dropseed/plain/commit/6a49f35a84bd))
- App-local packages (those inside the project root) are no longer redundantly emitted as `@source` entries in `.plain/tailwind.css`, since Tailwind already scans the project root by default. ([6a49f35a84bd](https://github.com/dropseed/plain/commit/6a49f35a84bd))
- `.plain/tailwind.css` is now generated with `@import` rules first and `@source` rules after, per the CSS spec requirement that `@import` precede other rules. ([6a49f35a84bd](https://github.com/dropseed/plain/commit/6a49f35a84bd))
- Path separators in the generated `.plain/tailwind.css` are normalized to POSIX forward slashes regardless of platform, since backslashes in CSS strings are escape sequences. ([6a49f35a84bd](https://github.com/dropseed/plain/commit/6a49f35a84bd))

### Upgrade instructions

- No changes required for project authors. After upgrading, your next Tailwind build will regenerate `.plain/tailwind.css`; expect new `@import "..."` lines if any of your installed packages ship a `tailwind.css`.
- Package authors: if you want to contribute design tokens, components, or custom variants to user Tailwind builds, add a `tailwind.css` file next to your package's `__init__.py`.

## [0.20.5](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.5) (2026-02-26)

### What's changed

- Added type annotations to `TAILWIND_SRC_PATH` and `TAILWIND_DIST_PATH` settings ([37e8a58ca9b5](https://github.com/dropseed/plain/commit/37e8a58ca9b5))

### Upgrade instructions

- No changes required.

## [0.20.4](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.4) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.20.3](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.3) (2026-02-04)

### What's changed

- Removed `@internalcode` decorator from `Tailwind`, `TailwindCSSExtension`, and entrypoint functions ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- No changes required.

## [0.20.2](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.2) (2026-01-28)

### What's changed

- Converted the `plain-tailwind` skill to a passive `.claude/rules/` file with path-based activation on `**/*.html` files ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory.

## [0.20.1](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.20.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.20.0) (2026-01-15)

### What's changed

- Internal version bump with no user-facing changes

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.19.0) (2026-01-13)

### What's changed

- Improved README documentation with better structure, more examples, and FAQs section ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.18.0) (2026-01-13)

### What's changed

- Internal version bump with no user-facing changes

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.17.0) (2025-12-04)

### What's changed

- Internal type annotation improvements ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.16.0) (2025-11-24)

### What's changed

- Internal version bump with no user-facing changes

### Upgrade instructions

- No changes required

## [0.15.4](https://github.com/dropseed/plain/releases/plain-tailwind@0.15.4) (2025-11-03)

### What's changed

- Internal version bump with no user-facing changes

### Upgrade instructions

- No changes required

## [0.15.3](https://github.com/dropseed/plain/releases/plain-tailwind@0.15.3) (2025-10-12)

### What's changed

- Removed outdated reference to Heroku buildpack in documentation ([ee4710a](https://github.com/dropseed/plain/commit/ee4710af07))

### Upgrade instructions

- No changes required

## [0.15.2](https://github.com/dropseed/plain/releases/plain-tailwind@0.15.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations to improve IDE and type checker support ([9b6882b](https://github.com/dropseed/plain/commit/9b6882bae7))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-tailwind@0.15.1) (2025-09-25)

### What's changed

- Improved Tailwind download performance by using larger chunk sizes (8MB) and optimized HTTP connection pooling ([9bf4eca](https://github.com/dropseed/plain/commit/9bf4eca61e))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.15.0) (2025-09-19)

### What's changed

- Added `plain-tailwind` standalone script for running Tailwind installation separately from Plain ([a9d1ab6](https://github.com/dropseed/plain/commit/a9d1ab6c18))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-tailwind@0.14.0) (2025-09-19)

### What's changed

- Added new `plain tailwind version` command to display the currently installed Tailwind CSS version ([4679a42](https://github.com/dropseed/plain/commit/4679a423b6))
- Minimum Python version requirement updated from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Update your Python environment to Python 3.13 or later

## [0.13.3](https://github.com/dropseed/plain/releases/plain-tailwind@0.13.3) (2025-09-03)

### What's changed

- Comprehensive README update with improved documentation structure, table of contents, and detailed usage examples ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Added AGENTS.md file with guidance for conditional Tailwind styling using `data-` attributes ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))

### Upgrade instructions

- No changes required

## [0.13.2](https://github.com/dropseed/plain/releases/plain-tailwind@0.13.2) (2025-07-07)

### What's changed

- The CLI now shows a progress bar while downloading the Tailwind standalone binary, so long downloads no longer appear to hang ([ec637aa](https://github.com/dropseed/plain/commit/ec637aa)).

### Upgrade instructions

- No changes required

## [0.13.1](https://github.com/dropseed/plain/releases/plain-tailwind@0.13.1) (2025-06-26)

### What's changed

- No user-facing changes in this patch release. Internal housekeeping of the CHANGELOG file only ([e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3e4612)).

### Upgrade instructions

- No changes required
