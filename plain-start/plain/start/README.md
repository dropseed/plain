# Plain Start

**Bootstrap a new Plain project from official starter templates.**

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
