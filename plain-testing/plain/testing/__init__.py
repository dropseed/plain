"""
Plain's own test runner.

This package is the engine: collection, assertion rewriting, execution,
and reporting. The test-authoring API (what test files import)
lives in `plain.test` in core — see README.md for the split.

Nothing in this package is meant to be imported. What it offers is the
`plain test` command, the `plain.testing` entry point group for packages,
and `tests/lifecycle.py` for a project. Every module's `__all__` is empty
to say so.
"""

__all__ = []
