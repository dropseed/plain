# plain.dev

**A single command that runs everything you need for local development.**

![Plain dev command example](https://github.com/dropseed/plain/assets/649496/3643bb64-a99b-4a8e-adab-8c6b81791ea9)

- [Overview](#overview)
- [Commands](#commands)
    - [`plain dev`](#plain-dev)
        - [Services](#services)
        - [Custom processes](#custom-processes)
    - [`plain dev services`](#plain-dev-services)
    - [`plain dev logs`](#plain-dev-logs)
    - [`plain pre-commit`](#plain-pre-commit)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain dev` command starts everything you need for local development with a single command:

```bash
plain dev
```

This will:

- Run preflight checks
- Execute pending migrations
- Start your development server with auto-reload
- Build and watch CSS with Tailwind (if installed)
- Start required services (like databases)
- Run any custom processes you've defined

## Commands

### `plain dev`

The [`plain dev`](./cli.py#cli) command does several things:

- Sets `PLAIN_CSRF_TRUSTED_ORIGINS` to localhost by default
- Runs `plain preflight` to check for any issues
- Executes any pending model migrations
- Starts `gunicorn` with `--reload`
- Serves HTTPS on port 8443 by default (uses the next free port if 8443 is taken and no port is specified)
- Runs `plain tailwind build --watch`, if [`plain.tailwind`](../../plain-tailwind/plain/tailwind/README.md) is installed
- Any custom process defined in `pyproject.toml` at `tool.plain.dev.run`
- Necessary services (ex. Postgres) defined in `pyproject.toml` at `tool.plain.dev.services`

#### Services

Use services to define databases or other processes that your app _needs_ to be functional. The services will be started automatically in `plain dev`, but also in `plain pre-commit` (so preflight and tests have a database).

Ultimately, how you run your development database is up to you. But a recommended starting point is to use Docker:

```toml
# pyproject.toml
[tool.plain.dev.services]
postgres = {cmd = "docker run --name app-postgres --rm -p 54321:5432 -v $(pwd)/.plain/dev/pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres postgres:15 postgres"}
```

#### Custom processes

Unlike [services](#services), custom processes are _only_ run during `plain dev`. This is a good place to run something like [ngrok](https://ngrok.com/) or a [Plain job worker](../../plain-jobs/plain/jobs/README.md), which you might need to use your local site, but don't need running for executing tests, for example.

```toml
# pyproject.toml
[tool.plain.dev.run]
    ngrok = {command = "ngrok http $PORT"}
```

### `plain dev services`

Starts your [services](#services) by themselves.
Logs are stored in `.plain/dev/logs/services/`.

### `plain dev logs`

Show output from recent `plain dev` runs.

Logs are stored in `.plain/dev/logs/run/`.

```bash
plain dev logs        # print last log
plain dev logs -f     # follow the latest log
plain dev logs --pid 1234
plain dev logs --path
```

### `plain pre-commit`

A built-in pre-commit hook that you can install with `plain pre-commit --install`.

Runs:

- `uv lock --check`, if using uv
- `plain check` (custom commands, code linting, preflight, migrations, tests)
- `plain build`

Custom commands can be defined in `pyproject.toml` at `tool.plain.check.run` and will run as part of `plain check`:

```toml
[tool.plain.check.run]
my-check = {cmd = "echo 'running my check'"}
```

## Settings

| Setting                     | Default            | Env var |
| --------------------------- | ------------------ | ------- |
| `DEV_REQUESTS_IGNORE_PATHS` | `["/favicon.ico"]` | -       |
| `DEV_REQUESTS_MAX`          | `50`               | -       |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I stop the development server?

You can stop the development server by pressing `Ctrl+C` in the terminal, or by running `plain dev --stop` if it was started in the background.

#### Can I run the server on a different port?

Yes, use the `--port` or `-p` option: `plain dev --port 8000`. If you don't specify a port, it will use 8443 or the next available port.

#### How do I run the server in the background?

Use `plain dev --start` to run the server in the background. You can then use `plain dev --stop` to stop it.

#### What's the difference between services and custom processes?

Services are processes that your app needs to function (like a database). They run during `plain dev` and also during `plain pre-commit`. Custom processes only run during `plain dev` and are typically for development conveniences like ngrok or a job worker.

#### Why am I seeing deprecation warnings?

The development server is configured to show `DeprecationWarning` and `PendingDeprecationWarning` messages so you can catch deprecated code before it breaks in future versions. You can override this by setting your own `PYTHONWARNINGS` environment variable.

## Installation

Install the `plain.dev` package from [PyPI](https://pypi.org/project/plain.dev/):

```bash
uv add plain.dev --dev
```

Note: The `plain.dev` package does not need to be added to `INSTALLED_PACKAGES`.
