# plain-start

**Bootstrap a new Plain project from official starter templates.**

- [Overview](#overview)
- [Starter templates](#starter-templates)
    - [App starter (default)](#app-starter-default)
    - [Bare starter](#bare-starter)
- [Options](#options)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can create a new Plain project with a single command:

```bash
uvx plain-start my-project
```

This clones the official app starter template, configures your project name, initializes a fresh git repository, and runs the installation script. When it finishes, you'll have a working project ready to go.

```bash
cd my-project
uv run plain dev
```

## Starter templates

Plain provides two official starter templates hosted on GitHub.

### App starter (default)

The app starter includes everything you need for a full-featured web application:

- Database ORM
- User authentication
- Admin interface
- Session management
- All core Plain packages

```bash
uvx plain-start my-app
```

### Bare starter

The bare starter is a minimal setup for when you want to start from scratch:

- Plain framework core only
- Development tools
- No database or auth

```bash
uvx plain-start my-project --type bare
```

## Options

### `--type`

Choose which starter template to use. Defaults to `app`.

```bash
uvx plain-start my-project --type bare
```

### `--no-install`

Skip running the `./scripts/install` script after cloning. Use this if you want to inspect the project before installing dependencies.

```bash
uvx plain-start my-project --no-install
cd my-project
# review the project structure...
./scripts/install
```

## FAQs

#### What happens during project creation?

The [`cli`](./cli.py#cli) command performs these steps:

1. Clones the starter repository (shallow clone for speed)
2. Removes the `.git` directory and initializes a fresh repository
3. Updates the project name in `pyproject.toml`
4. Runs `./scripts/install` to set up dependencies (unless `--no-install` is used)

#### Where are the starter templates hosted?

The starter templates are hosted on GitHub:

- App starter: https://github.com/dropseed/plain-starter-app
- Bare starter: https://github.com/dropseed/plain-starter-bare

#### What if the directory already exists?

The command will exit with an error. You'll need to choose a different project name or remove the existing directory first.

#### What if the install script fails?

If the installation script fails, you'll see a warning message. You can try running `./scripts/install` manually after investigating the issue.

## Installation

The recommended way to use `plain-start` is with `uvx`, which runs the command without needing to install it first:

```bash
uvx plain-start my-project
```

If you prefer to install it globally:

```bash
uv tool install plain-start
plain-start my-project
```
