# plain-templates changelog

## [0.2.0](https://github.com/dropseed/plain/releases/plain-templates@0.2.0) (2026-05-13)

### What's changed

- **`TemplateView.handle_exception` renders `{status}.html`.** The error-template handling that lived in `plain` core's exception handler now sits on `TemplateView` itself: `404.html` for `NotFoundError404`, `500.html` for unhandled errors, etc., with context `{request, status_code, exception, DEBUG}`. Falls through to plain-text rendering (via `raise exc from None`) on `TemplateFileMissing`; logs and returns a bare-status `Response` on any other render failure so `_respond_to_exception` can still attach `response.exception`. ([90d8fd983b](https://github.com/dropseed/plain/commit/90d8fd983b))
- **New `NotFoundView` catchall view.** `before_request` raises `NotFoundError404` before method dispatch, so every HTTP method renders the styled 404 instead of falling through to a 405. Mount it as the last route — `path("<path:_>", NotFoundView)` — for a styled 404 on unmatched URLs. Pairs with the catchall route semantics added in `plain` 0.145.0. ([90d8fd983b](https://github.com/dropseed/plain/commit/90d8fd983b))

### Upgrade instructions

- **If you have a `404.html` template, mount `NotFoundView` as the last route** — otherwise unmatched URLs now return plain-text `404 Not Found` instead of rendering your template. URL-resolution failures happen before any view runs, so plain core's exception handler can't reach `TemplateView.handle_exception`; the catchall route is what gives those requests a `TemplateView` to render through.

    ```python
    from plain.templates.views import NotFoundView
    from plain.urls import Router, path

    class AppRouter(Router):
        urls = [
            # ... your routes ...
            path("<path:_>", NotFoundView),
        ]
    ```

- Apps that previously relied on plain core auto-rendering `{status}.html` will still see those templates render for exceptions raised _inside_ a view — `TemplateView.handle_exception` fires whenever an exception escapes a `TemplateView` subclass. For pre-view failures (URL resolution, middleware) plain core stays in plain text unless you mount `NotFoundView` (above) or otherwise route through a `TemplateView`.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-templates@0.1.0) (2026-05-12)

### What's changed

- First release. `plain.templates` is now a separate package, extracted from `plain` core ([19b622a7ca](https://github.com/dropseed/plain/commit/19b622a7ca)). It owns:
    - The Jinja2 engine, `DefaultEnvironment`, the `TEMPLATES_JINJA_ENVIRONMENT` setting
    - `Template` and `TemplateFileMissing`
    - `register_template_global`, `register_template_filter`, `register_template_extension`
    - The template-rendering view bases: `TemplateView`, `FormView`, `DetailView`, `CreateView`, `UpdateView`, `DeleteView`, `ListView` at `plain.templates.views`
    - The `{status_code}.html` error rendering wired through `plain` core's framework default exception handler (lazy import — degrades to plain text if this package isn't installed)

### Upgrade instructions

- Install the package and add it to `INSTALLED_PACKAGES` — see the [`plain` 0.143.0 release notes](../../../plain/plain/CHANGELOG.md) for the full migration.
