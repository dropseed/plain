# plain.preflight

**System checks that validate your settings and environment before running your application.**

- [Overview](#overview)
- [Running preflight checks](#running-preflight-checks)
    - [Development](#development)
    - [Deployment](#deployment)
    - [JSON output](#json-output)
- [Built-in checks](#built-in-checks)
- [Custom preflight checks](#custom-preflight-checks)
    - [Basic checks](#basic-checks)
    - [Deployment-only checks](#deployment-only-checks)
    - [Warnings vs errors](#warnings-vs-errors)
- [Silencing checks](#silencing-checks)
    - [Silencing entire checks](#silencing-entire-checks)
    - [Silencing specific results](#silencing-specific-results)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Preflight checks help you catch configuration problems early. You can run checks to verify that settings are valid, directories exist, URL patterns are correct, and security requirements are met before your application starts.

```python
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check("custom.database_connection")
class CheckDatabaseConnection(PreflightCheck):
    """Verify database is reachable."""

    def run(self) -> list[PreflightResult]:
        from plain.models import connection

        try:
            connection.ensure_connection()
        except Exception as e:
            return [
                PreflightResult(
                    fix=f"Database connection failed: {e}. Check your DATABASE_URL.",
                    id="custom.database_unreachable",
                )
            ]
        return []
```

When you run `plain preflight`, your check runs alongside the built-in checks:

```bash
$ plain preflight
Running preflight checks...
Check: custom.database_connection ✔
Check: files.upload_temp_dir ✔
Check: settings.unused_env_vars ✔
Check: urls.config ✔

4 passed
```

## Running preflight checks

### Development

Run preflight checks at any time:

```bash
plain preflight
```

If you use [`plain.dev`](/plain-dev/README.md) for local development, preflight checks run automatically when you start `plain dev`.

### Deployment

Add `--deploy` to include deployment-specific checks like `SECRET_KEY` strength, `DEBUG` mode, and `ALLOWED_HOSTS`:

```bash
plain preflight --deploy
```

This should be part of your deployment process. If any check fails (returns errors, not warnings), the command exits with code 1.

### JSON output

For CI/CD pipelines or programmatic access, use JSON output:

```bash
plain preflight --format json
```

```json
{
  "passed": true,
  "checks": [
    {
      "name": "files.upload_temp_dir",
      "passed": true,
      "issues": []
    }
  ]
}
```

Use `--quiet` to suppress progress output and only show errors.

## Built-in checks

Plain includes these checks out of the box:

| Check                           | Description                                              | Deploy only |
| ------------------------------- | -------------------------------------------------------- | ----------- |
| `files.upload_temp_dir`         | Validates `FILE_UPLOAD_TEMP_DIR` exists                  | No          |
| `settings.unused_env_vars`      | Detects env vars that look like settings but aren't used | No          |
| `urls.config`                   | Validates URL patterns for common issues                 | No          |
| `security.secret_key`           | Validates `SECRET_KEY` strength                          | Yes         |
| `security.secret_key_fallbacks` | Validates `SECRET_KEY_FALLBACKS` strength                | Yes         |
| `security.debug`                | Ensures `DEBUG` is False                                 | Yes         |
| `security.allowed_hosts`        | Ensures `ALLOWED_HOSTS` is not empty                     | Yes         |

## Custom preflight checks

### Basic checks

Create a check by subclassing [`PreflightCheck`](./checks.py#PreflightCheck) and using the [`@register_check`](./registry.py#register_check) decorator:

```python
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check("custom.redis_connection")
class CheckRedisConnection(PreflightCheck):
    """Verify Redis cache is reachable."""

    def run(self) -> list[PreflightResult]:
        from plain.cache import cache

        try:
            cache.set("preflight_test", "ok", timeout=1)
        except Exception as e:
            return [
                PreflightResult(
                    fix=f"Redis connection failed: {e}",
                    id="custom.redis_unreachable",
                )
            ]
        return []
```

Place this in a `preflight.py` file in your app directory. Plain autodiscovers `preflight.py` modules when running checks.

### Deployment-only checks

For checks that only matter in production, add `deploy=True`:

```python
@register_check("custom.ssl_certificate", deploy=True)
class CheckSSLCertificate(PreflightCheck):
    """Verify SSL certificate is valid and not expiring soon."""

    def run(self) -> list[PreflightResult]:
        # Check certificate expiration...
        if days_until_expiry < 30:
            return [
                PreflightResult(
                    fix=f"SSL certificate expires in {days_until_expiry} days.",
                    id="custom.ssl_expiring_soon",
                )
            ]
        return []
```

### Warnings vs errors

By default, [`PreflightResult`](./results.py#PreflightResult) represents an error that fails the preflight. For non-critical issues, use `warning=True`:

```python
PreflightResult(
    fix="Consider enabling gzip compression for better performance.",
    id="custom.gzip_disabled",
    warning=True,  # Won't cause preflight to fail
)
```

Warnings display with a yellow indicator but don't cause the command to exit with an error code.

## Silencing checks

### Silencing entire checks

To skip a check entirely, add its name to `PREFLIGHT_SILENCED_CHECKS`:

```python
# app/settings.py
PREFLIGHT_SILENCED_CHECKS = [
    "security.debug",  # We intentionally run with DEBUG=True in staging
]
```

### Silencing specific results

To silence individual result IDs (not the whole check), use `PREFLIGHT_SILENCED_RESULTS`:

```python
# app/settings.py
PREFLIGHT_SILENCED_RESULTS = [
    "security.secret_key_weak",  # Using a known weak key in testing
]
```

## FAQs

#### What's the difference between a check name and a result ID?

The check name (like `security.secret_key`) identifies the check class. The result ID (like `security.secret_key_weak`) identifies a specific issue that check can report. A single check can return multiple different result IDs.

#### Where should I put custom preflight checks?

Create a `preflight.py` file in your app directory. Plain autodiscovers these modules when running `plain preflight`.

#### How do I run checks programmatically?

Use the [`run_checks`](./registry.py#run_checks) function:

```python
from plain.preflight import run_checks

for check_class, name, results in run_checks(include_deploy_checks=True):
    for result in results:
        print(f"{name}: {result.fix}")
```

#### Can I attach additional context to a result?

Use the `obj` parameter to attach a related object:

```python
PreflightResult(
    fix="Invalid URL pattern",
    id="urls.invalid_pattern",
    obj=some_url_pattern,  # Will be included in output
)
```

## Installation

`plain.preflight` is included with the `plain` package. No additional installation is required.
