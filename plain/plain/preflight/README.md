# Preflight

**System checks for Plain applications.**

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

Use the `@register_check` decorator to add your own preflight check to the system. Just make sure that particular Python module is somehow imported so the check registration runs.

```python
from plain.preflight import register_check, Error


@register_check
def custom_check(package_configs, **kwargs):
    return Error("This is a custom error message.", id="custom.C001")
```

For deployment-specific checks, add the `deploy` argument to the decorator.

```python
@register_check(deploy=True)
def custom_deploy_check(package_configs, **kwargs):
    return Error("This is a custom error message for deployment.", id="custom.D001")
```

## Silencing preflight checks

The `settings.PREFLIGHT_SILENCED_CHECKS` setting can be used to silence individual checks by their ID (ex. `security.W020`).

```python
# app/settings.py
PREFLIGHT_SILENCED_CHECKS = [
    "security.W020",
]
```
