# plain.vendor

**Download CDN scripts and styles as vendored dependencies.**

- [What about source maps?](#what-about-source-maps)
- [Installation](#installation)

## What about source maps?

It's fairly common right now to get an error during `plain build` that says it can't find the source map for one of your vendored files.
Right now, the fix is add the source map itself to your vendored dependencies too.
In the future `plain vendor` might discover those during the vendoring process and download them automatically with the compiled files.

## Installation

Install the `plain.vendor` package from [PyPI](https://pypi.org/project/plain.vendor/):

```bash
uv add plain.vendor
```
