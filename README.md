# Plain

**A full-stack Python framework, redesigned for coding agents.**

## Get started

```
mkdir my-app && cd my-app && claude "$(curl -sSf https://plainframework.com/start.md)"
```

Also works with Codex, Amp, OpenCode, or your agent of choice.

## Why Plain?

Explicit, typed, and predictable. What's good for humans is good for agents.

Here's what Plain code looks like:

```python
# app/users/models.py
from plain import models
from plain.models import types
from plain.passwords.models import PasswordField

@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    password: str = PasswordField()
    display_name: str = types.CharField(max_length=100)
    is_admin: bool = types.BooleanField(default=False)
    created_at: datetime = types.DateTimeField(auto_now_add=True)

    query: models.QuerySet[User] = models.QuerySet()

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(fields=["email"], name="unique_email"),
        ],
    )
```

Views are class-based:

```python
# app/users/views.py
from plain.views import DetailView
from .models import User

class UserDetail(DetailView):
    template_name = "users/detail.html"

    def get_object(self):
        return User.query.get(pk=self.url_kwargs["pk"])
```

URLs use a `Router` class:

```python
# app/users/urls.py
from plain.urls import Router, path
from . import views

class UsersRouter(Router):
    namespace = "users"
    urls = [
        path("<int:pk>/", views.UserDetail),
    ]
```

## Agent tooling

Plain projects include built-in tooling that agents use automatically.

**Rules** — Always-on guardrails stored in project rules files (e.g. `.claude/rules/` for Claude Code). Short files (~50 lines) that prevent the most common mistakes.

**Docs** — Full framework documentation, accessible on demand from the command line:

```
plain docs models                      # full docs
plain docs models --section querying   # one section
plain docs models --api                # typed signatures only
plain docs --search "queryset"         # search across all packages
```

**Skills** — End-to-end workflows triggered by slash commands:

- `/plain-install` — add a new package and walk through setup
- `/plain-upgrade` — bump versions, read changelogs, apply breaking changes, run checks
- `/plain-optimize` — capture performance traces, identify slow queries and N+1 problems, apply fixes
- `/plain-bug` — collect context and submit a bug report as a GitHub issue

## CLI

All commands run with `uv run` (e.g. `uv run plain dev`).

- `plain dev` — start dev server with auto-reload and HTTPS
- `plain fix` — format and lint Python, CSS, and JS in one command
- `plain check` — linting, preflight, migration, and test validation
- `plain test` — run tests (pytest)
- `plain docs --api` — public API surface, formatted for LLMs

## Stack

Plain is opinionated. These are the technologies it's built on:

- **Python:** 3.13+
- **Database:** Postgres
- **Templates:** Jinja2
- **Frontend:** htmx, Tailwind CSS
- **Python tooling:** uv (packages), ruff (lint/format), ty (type checking) — all from Astral
- **JavaScript tooling:** oxc (lint/format), esbuild (bundling)
- **Testing:** pytest

## Packages

29 first-party packages, one framework. All with built-in docs.

**Foundation:**
- [plain](https://plainframework.com/docs/plain/plain/) — core framework
- [plain.models](https://plainframework.com/docs/plain-models/plain/models/) — database ORM
- [plain.auth](https://plainframework.com/docs/plain-auth/plain/auth/) — authentication
- [plain.sessions](https://plainframework.com/docs/plain-sessions/plain/sessions/) — session storage

**Backend:**
- [plain.api](https://plainframework.com/docs/plain-api/plain/api/) — REST APIs
- [plain.jobs](https://plainframework.com/docs/plain-jobs/plain/jobs/) — background jobs
- [plain.email](https://plainframework.com/docs/plain-email/plain/email/) — sending email
- [plain.cache](https://plainframework.com/docs/plain-cache/plain/cache/) — caching layer
- [plain.redirection](https://plainframework.com/docs/plain-redirection/plain/redirection/) — URL redirects
- [plain.vendor](https://plainframework.com/docs/plain-vendor/plain/vendor/) — vendored dependencies

**Frontend:**
- [plain.htmx](https://plainframework.com/docs/plain-htmx/plain/htmx/) — dynamic UI
- [plain.tailwind](https://plainframework.com/docs/plain-tailwind/plain/tailwind/) — CSS framework
- [plain.elements](https://plainframework.com/docs/plain-elements/plain/elements/) — HTML components
- [plain.pages](https://plainframework.com/docs/plain-pages/plain/pages/) — static pages
- [plain.esbuild](https://plainframework.com/docs/plain-esbuild/plain/esbuild/) — JS bundling

**Development:**
- [plain.dev](https://plainframework.com/docs/plain-dev/plain/dev/) — local server
- [plain.pytest](https://plainframework.com/docs/plain-pytest/plain/pytest/) — testing helpers
- [plain.toolbar](https://plainframework.com/docs/plain-toolbar/plain/toolbar/) — debug toolbar
- [plain.code](https://plainframework.com/docs/plain-code/plain/code/) — code formatting
- [plain.tunnel](https://plainframework.com/docs/plain-tunnel/plain/tunnel/) — dev tunneling
- [plain.start](https://plainframework.com/docs/plain-start/plain/start/) — project starter

**Production:**
- [plain.admin](https://plainframework.com/docs/plain-admin/plain/admin/) — database admin
- [plain.observer](https://plainframework.com/docs/plain-observer/plain/observer/) — request tracing
- [plain.flags](https://plainframework.com/docs/plain-flags/plain/flags/) — feature flags
- [plain.scan](https://plainframework.com/docs/plain-scan/plain/scan/) — security scanning
- [plain.pageviews](https://plainframework.com/docs/plain-pageviews/plain/pageviews/) — analytics
- [plain.support](https://plainframework.com/docs/plain-support/plain/support/) — support tickets

**Users:**
- [plain.passwords](https://plainframework.com/docs/plain-passwords/plain/passwords/) — password auth
- [plain.oauth](https://plainframework.com/docs/plain-oauth/plain/oauth/) — social login
- [plain.loginlink](https://plainframework.com/docs/plain-loginlink/plain/loginlink/) — magic links

## About

Plain is a fork of [Django](https://www.djangoproject.com/), driven by ongoing development at [PullApprove](https://www.pullapprove.com/) — with the freedom to reimagine it for the agentic era.

- Docs: https://plainframework.com/docs/
- Source: https://github.com/dropseed/plain
- Getting started: https://plainframework.com/start/
- License: [BSD-3](https://github.com/dropseed/plain/blob/main/LICENSE)
