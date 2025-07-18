# Plain

**Plain is a web framework for building products with Python.**

The core `plain` package provides the backbone of a Python web application (similar to [Flask](https://flask.palletsprojects.com/en/stable/)), while the additional first-party packages can power a more fully-featured database-backed app (similar to [Django](https://www.djangoproject.com/)).

All Plain packages are designed to work together and use [PEP 420](https://peps.python.org/pep-0420/) to share the `plain` namespace.

To quickly get started with Plain, visit [plainframework.com/start/](https://plainframework.com/start/).

## Core Modules

The `plain` package includes everything you need to start handling web requests with Python:

- [assets](./assets/README.md) - Serve static files and assets.
- [cli](./cli/README.md) - The `plain` CLI, powered by Click.
- [csrf](./csrf/README.md) - Cross-Site Request Forgery protection.
- [forms](./forms/README.md) - HTML forms and form validation.
- [http](./http/README.md) - HTTP request and response handling.
- [logs](./logs/README.md) - Logging configuration and utilities.
- [preflight](./preflight/README.md) - Preflight checks for your app.
- [runtime](./runtime/README.md) - Runtime settings and configuration.
- [templates](./templates/README.md) - Jinja2 templates and rendering.
- [test](./test/README.md) - Test utilities and fixtures.
- [urls](./urls/README.md) - URL routing and request dispatching.
- [views](./views/README.md) - Class-based views and request handlers.

## Foundational Packages

- [plain.models](/plain-models/plain/models/README.md) - Define and interact with your database models.
- [plain.cache](/plain-cache/plain/cache/README.md) - A database-driven general purpose cache.
- [plain.email](/plain-email/plain/email/README.md) - Send emails with SMTP or custom backends.
- [plain.sessions](/plain-sessions/plain/sessions/README.md) - User sessions and cookies.
- [plain.worker](/plain-worker/plain/worker/README.md) - Background jobs stored in the database.
- [plain.api](/plain-api/plain/api/README.md) - Build APIs with Plain views.

## Auth Packages

- [plain.auth](/plain-auth/plain/auth/README.md) - User authentication and authorization.
- [plain.oauth](/plain-oauth/plain/oauth/README.md) - OAuth authentication and API access.
- [plain.passwords](/plain-passwords/plain/passwords/README.md) - Password-based login and registration.
- [plain.loginlink](/plain-loginlink/plain/loginlink/README.md) - Login links for passwordless authentication.

## Admin Packages

- [plain.admin](/plain-admin/plain/admin/README.md) - An admin interface for back-office tasks.
- [plain.flags](/plain-flags/plain/flags/README.md) - Feature flags.
- [plain.support](/plain-support/plain/support/README.md) - Customer support forms.
- [plain.redirection](/plain-redirection/plain/redirection/README.md) - Redirects managed in the database.
- [plain.pageviews](/plain-pageviews/plain/pageviews/README.md) - Basic self-hosted page view tracking and reporting.
- [plain.observer](/plain-observer/plain/observer/README.md) - On-page telemetry reporting.

## Dev Packages

- [plain.dev](/plain-dev/plain/dev/README.md) - A single command for local development.
- [plain.pytest](/plain-pytest/plain/pytest/README.md) - Pytest fixtures and helpers.
- [plain.code](/plain-code/plain/code/README.md) - Code formatting and linting.
- [plain.tunnel](/plain-tunnel/plain/tunnel/README.md) - Expose your local server to the internet.

## Frontend Packages

- [plain.tailwind](/plain-tailwind/plain/tailwind/README.md) - Tailwind CSS integration without Node.js.
- [plain.htmx](/plain-htmx/plain/htmx/README.md) - HTMX integrated into views and templates.
- [plain.elements](/plain-elements/plain/elements/README.md) - Server-side HTML components.
- [plain.pages](/plain-pages/plain/pages/README.md) - Static pages with Markdown and Jinja2.
- [plain.esbuild](/plain-esbuild/plain/esbuild/README.md) - Simple JavaScript bundling and minification.
- [plain.vendor](/plain-vendor/plain/vendor/README.md) - Vendor JavaScript and CSS libraries.
