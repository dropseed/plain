"""
The test runner: collection, assertion rewriting, execution, and reporting.

Nothing in this package is meant to be imported. What it offers is the
`plain test` command, the `plain.test` entry point group for packages, and
`tests/lifecycle.py` for a project. Every module's `__all__` is empty to say
so. What a test file imports is in `plain.test` itself.

The runner knows nothing about the web. It imports `CollectedTest`,
`TestLifecycle`, `TestSkipped`, `TestDefinitionError` and the decorators'
attribute names from the package around it, and nothing else.
"""

__all__ = []
