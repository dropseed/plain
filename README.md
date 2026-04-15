# Plain

**The Python web framework for building apps.**

Originally a fork of Django, reshaped over years of real use.
Ready for the era of agents.

## Get started

Start with an agent (Claude, Codex, Amp, OpenCode, or your agent of choice):

```
mkdir my-app && cd my-app && claude "$(curl -sSf https://plainframework.com/start.md)"
```

Or start with uv directly:

```
uvx plain-start my-app
```

Full walkthrough: https://plainframework.com/start/

## What Plain code looks like

Explicit, typed, and predictable. What's good for humans is good for AI.

Models are Postgres-only:

```python
# app/users/models.py
from plain import postgres
from plain.postgres import types
from plain.postgres.functions import Now
from plain.passwords.models import PasswordField

@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    password: str = PasswordField()
    display_name: str = types.CharField(max_length=100)
    is_admin: bool = types.BooleanField(default=False)
    created_at: datetime = types.DateTimeField(default=Now())

    query: postgres.QuerySet[User] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="unique_email"),
        ],
    )
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

Templates are Jinja:

```html
{# app/users/templates/users/detail.html #}
{% extends "base.html" %}

{% block content %}
<h1>{{ user.display_name }}</h1>
<p>Joined {{ user.created_at.strftime("%B %Y") }}</p>
{% endblock %}
```

## An opinionated stack

Python where you want it, JS where you need it.

- **Python:** 3.13+
- **Database:** Postgres
- **Templates:** Jinja2
- **Frontend:** htmx, Tailwind CSS
- **Python tooling:** uv (packages), ruff (lint/format), ty (type checking)
- **JavaScript tooling:** oxc (lint/format), esbuild (bundling)
- **Testing:** pytest

Models declare fields as annotated attributes, and that typing carries through views, forms, and URLs. `plain check` runs `ty` on every pass — what your IDE shows, CI enforces, and agents read from the same signatures.

## Observability at the core

OpenTelemetry traces, a built-in request observer, and slow-query detection ship in the box. The first time an N+1 matters, you already have the tools to see it.

## Agents at the forefront

Predictable APIs, typed signatures, and on-demand docs happen to be what both people and coding agents need. Plain projects also ship tooling that agents use automatically.

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

## First-party ecosystem

30 packages, one framework. All with built-in docs. Decisions that usually take a sprint are already made.

**Foundation:**

- [plain](https://plainframework.com/docs/plain/plain/) — core framework
- [plain.postgres](https://plainframework.com/docs/plain-postgres/plain/postgres/) — database ORM
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
- [plain.portal](https://plainframework.com/docs/plain-portal/plain/portal/) — remote shell and file transfer
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

Plain is a fork of [Django](https://www.djangoproject.com/), started in the stone age of 2023 and driven by real use at [PullApprove](https://www.pullapprove.com/).

- Docs: https://plainframework.com/docs/
- Source: https://github.com/dropseed/plain
- Getting started: https://plainframework.com/start/
- License: [BSD-3](https://github.com/dropseed/plain/blob/main/LICENSE)
