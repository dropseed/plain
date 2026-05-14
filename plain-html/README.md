# plain.html

HTML-aware template engine for Plain. Components are template files, no registry, contextual autoescape, statically checkable.

This package is being built per the design in [plain-template-language.md](../plain-template-language.md) and the phased plan in [plain-html-implementation-plan.md](../plain-html-implementation-plan.md).

Current status: **Phase 0 tracer bullet.** Enough engine surface to render a small `.plain` template end-to-end and compare output against an equivalent Jinja template. See `tests/parity/` for paired fixtures and the diff harness.

## Security

plain.html treats two things very differently.

**Template authors are trusted.** Frontmatter `imports:` runs at module load; `{python expressions}` run at render time. These are application code, same trust level as `views.py`. plain.html does **not** sandbox templates. Do not render user-uploaded templates with this engine — there is no safe configuration that supports it.

**Data passed to templates is hostile by default.** Every `{expr}` in text body or attribute value runs through the appropriate escape for its context. Authors opt out per-call with `mark_safe(value)` or `Markup(value)` (the same name, both auto-imported in every compiled module) — these calls are deliberately greppable.

### Per-context escape table

| Position                                                                                      | Escape                          | Notes                                                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Text body (`<p>{x}</p>`)                                                                      | HTML entity escape              | `<` → `&lt;`, etc.                                                                                                                                                                                                                                                                 |
| Generic attribute (`<a class={x}>`)                                                           | HTML entity escape              | Same handler as text.                                                                                                                                                                                                                                                              |
| URL attribute (`href`, `src`, `action`, `formaction`, `xlink:href`, `data`, `poster`, `cite`) | Scheme allow-list + HTML escape | Schemes outside `{http, https, mailto, tel, ftp, ftps}` cause the whole attribute to be omitted.                                                                                                                                                                                   |
| Event-handler attribute (`onclick=`, `on*=`)                                                  | **Compile error**               | HTML escape doesn't protect a JS context. Author must wrap the value in `mark_safe(...)` to opt in, or write a literal handler.                                                                                                                                                    |
| `<script>` body                                                                               | Opaque text                     | `{expr}` syntax is **not** parsed inside script bodies — the content is emitted verbatim. To inject data into JS, set a `data-*` attribute (auto-escaped) and read it in JS, or use `Markup(json.dumps(value))` and put it in a separate `<script type="application/json">` block. |
| `<style>` body                                                                                | Opaque text                     | Same as `<script>`.                                                                                                                                                                                                                                                                |

### What we do not protect against

- A template author writing `mark_safe(user_input)`. That call is the documented opt-out; auditing it is the author's responsibility.
- Bugs in the application's escape calls outside the template path.
- Open-redirect attacks: a `href="https://attacker.example.com/..."` is on the allow-list (it's a valid `https://` URL) and will render. Validating destination hosts is application logic.

### Implementation notes

- YAML frontmatter loading uses `python-frontmatter`'s safe loader — `!!python/object/apply` tags raise `ConstructorError` and do not execute.
- The compiler's emitted Python sets `__template_source__` on each module so tracebacks point at the original `.plain.html` source.
- Compile cache (Phase 5e, not yet shipped) will write to a project-local directory with mode `0700`. Do not relax those permissions.
