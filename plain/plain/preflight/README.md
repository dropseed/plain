# Preflight

**System checks for Plain applications.**

- [Overview](#overview)
- [Development](#development)
- [Deployment](#deployment)
- [Custom preflight checks](#custom-preflight-checks)
- [Silencing preflight checks](#silencing-preflight-checks)

## Overview

Preflight checks help identify issues with your settings or environment before running your application.

```bash
plain preflight
```

## Development

If you use [`plain.dev`](/plain-dev/README.md) for local development, the Plain preflight command is run automatically when you run `plain dev`.

## Deployment

The `plain preflight` command should often be part of your deployment process. Make sure to add the `--deploy` flag to the command to run checks that are only relevant in a production environment.

```bash
plain preflight --deploy
```

## Custom preflight checks

Use the `@register_check` decorator to add your own preflight check to the system. Create a class that inherits from `PreflightCheck` and implements a `run()` method that returns a list of `PreflightResult` objects.

```python
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check("custom.example")
class CustomCheck(PreflightCheck):
    """Description of what this check validates."""

    def run(self) -> list[PreflightResult]:
        # Your check logic here
        if some_condition:
            return [
                PreflightResult(
                    fix="This is a custom error message.",
                    id="custom.example_failed",
                )
            ]
        return []
```

For deployment-specific checks, add `deploy=True` to the decorator.

```python
@register_check("custom.deploy_example", deploy=True)
class CustomDeployCheck(PreflightCheck):
    """Description of what this deployment check validates."""

    def run(self) -> list[PreflightResult]:
        # Your deployment check logic here
        if some_deploy_condition:
            return [
                PreflightResult(
                    fix="This is a custom error message for deployment.",
                    id="custom.deploy_example_failed",
                )
            ]
        return []
```

## Silencing preflight checks

The `settings.PREFLIGHT_SILENCED_CHECKS` setting can be used to silence individual checks by their ID (ex. `security.E020`).

```python
# app/settings.py
PREFLIGHT_SILENCED_CHECKS = [
    "security.E020",  # Allow empty ALLOWED_HOSTS in deployment
]
```
