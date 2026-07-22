# plain-templates changelog

## [0.5.0](https://github.com/dropseed/plain/releases/plain-templates@0.5.0) (2026-07-21)

### What's changed

- **`ListView` can paginate.** Set `page_size` and the objects are wrapped in a `Paginator`, the page number is read from the `?page` query param (invalid values clamp to the first or last page), and the current `Page` is what lands in the template context as `objects` — iterate it exactly like the full list. Override `get_page_size()` to compute the size per request; return `None` (the default) to render the full list. ([4cf9576c12](https://github.com/dropseed/plain/commit/4cf9576c12))
- **`page_obj` is in the list template context**, holding the current `Page` for rendering pagination controls, or `None` when pagination is off. An empty `Page` is falsy, so test with `{% if page_obj is not none %}` rather than a plain truthiness check. ([4cf9576c12](https://github.com/dropseed/plain/commit/4cf9576c12))

### Upgrade instructions

- No changes required. `ListView` renders the full list as before until you set `page_size`.
- A paginated queryset needs a deterministic order (an `order_by()` or a model default) — unordered results can shift between pages.

## [0.4.0](https://github.com/dropseed/plain/releases/plain-templates@0.4.0) (2026-06-07)

### What's changed

- **`CreateView`, `UpdateView`, and `DeleteView` adapt to the new `ModelForm.create()`/`update()` split** (`plain-postgres` 0.107.0). `CreateView.form_valid` now calls `form.create()`; `UpdateView.form_valid` now calls `form.update()` and assigns the result to `self.object` (it previously left `self.object` unset). ([66634f5af9](https://github.com/dropseed/plain/commit/66634f5af9))
- **`DeleteView` no longer routes deletion through the form.** Its `EmptyDeleteForm` used to take the instance and define a `save()` that deleted it; it is now a plain fieldless confirmation `Form`, and `DeleteView.form_valid` calls `self.object.delete()` directly. The `get_form_kwargs` override that injected `instance` is removed. ([66634f5af9](https://github.com/dropseed/plain/commit/66634f5af9))

### Upgrade instructions

- If you subclass `CreateView` or `UpdateView` and override `form_valid` to call `form.save()`, switch to `form.create()` / `form.update()`. Using these views with a `ModelForm` requires `plain-postgres>=0.107.0` (which provides `create()`/`update()`).
- If you subclass `DeleteView` and relied on `EmptyDeleteForm` accepting an `instance` kwarg or its `save()` method, note the form is now fieldless and deletion happens in `form_valid` via `self.object.delete()` — override `form_valid` for custom delete behavior.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-templates@0.3.0) (2026-05-16)

### What's changed

- **`TemplateView.render_template()` replaced by `render(**context)`.** The new method returns a `Response`(not a`str`) and layers any keyword context over `get_template_context()`, so a handler can push what the template needs straight in — `self.render(product=product)`— instead of stashing it on`self`for`get_template_context()`to read back. Called with no arguments it renders`get_template_context()`as-is, which is what`get()` does. ([d88e0556b0](https://github.com/dropseed/plain/commit/d88e0556b0))
- **`FormView.form_invalid` removed.** `post()` now re-renders an invalid form directly via `self.render(form=form)`; `form_valid` is unchanged. ([ddbbfb05dc](https://github.com/dropseed/plain/commit/ddbbfb05dc))

### Upgrade instructions

- Replace `render_template()` with `render()`. Since `render()` returns a `Response`, `Response(self.render_template())` becomes `self.render()`. Per-render context can be passed as keyword arguments (`self.render(form=form)`) instead of going through `get_template_context()`.
- If you overrode `FormView.form_invalid`, move that logic into a `render()` or `post()` override — the invalid-form path now calls `self.render(form=form)`.

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
