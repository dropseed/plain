# Plain Start

**Bootstrap a new Plain project from official starter templates.**

## Contents

- [Overview](#overview)
- [Starter types](#starter-types)
- [Options](#options)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain-start` command provides a streamlined way to create new Plain projects from official starter templates. It clones the starter repository, configures your project name, and optionally runs the installation script to get you up and running quickly.

Basic usage:

```bash
uvx plain-start my-project
cd my-project
uv run plain dev
```

This creates a new project called `my-project` using the full app starter template (with ORM, auth, admin, etc.).

## Starter types

Plain provides two official starter templates:

### App starter (default)

The app starter includes a full-featured setup with:

- Database ORM
- Authentication system
- Admin interface
- Session management
- All core Plain packages

Create an app starter project:

```bash
uvx plain-start my-app
# or explicitly:
uvx plain-start my-app --type app
```

### Bare starter

The bare starter is a minimal setup with:

- Plain framework core
- Development tools only
- No database or auth by default

Create a bare starter project:

```bash
uvx plain-start my-project --type bare
```

## Options

The [`cli`](./cli.py#cli) command accepts the following options:

### `--type`

Choose between `app` (default) or `bare` starter templates.

```bash
uvx plain-start my-project --type bare
```

### `--no-install`

Skip running the `./scripts/install` script after cloning. Useful if you want to review the project structure before installing dependencies.

```bash
uvx plain-start my-project --no-install
```

## FAQs

#### What does the install script do?

The `./scripts/install` script sets up your Python environment using `uv`, installs dependencies, and runs initial migrations for the database. You can always run it manually later if you use `--no-install`.

#### Can I use plain-start with a specific version?

Yes, you can specify a version using `uvx`:

```bash
uvx plain-start@0.1.0 my-project
```

#### What gets replaced in the project?

The command updates the `name` field in your `pyproject.toml` to match your project name. All other configuration remains as-is for you to customize.

## Installation

Install and run `plain-start` using `uvx` (recommended):

```bash
uvx plain-start my-project
```

Or install it globally:

```bash
uv tool install plain-start
plain-start my-project
```

The command clones the starter template, configures your project name, initializes a new git repository, and runs the installation script (unless you pass `--no-install`).
