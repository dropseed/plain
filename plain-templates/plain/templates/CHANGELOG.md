# plain-templates changelog

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
