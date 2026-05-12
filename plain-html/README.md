# plain.html

HTML-aware template engine for Plain. Components are template files, no registry, contextual autoescape, statically checkable.

This package is being built per the design in [plain-template-language.md](../plain-template-language.md) and the phased plan in [plain-html-implementation-plan.md](../plain-html-implementation-plan.md).

Current status: **Phase 0 tracer bullet.** Enough engine surface to render a small `.plain` template end-to-end and compare output against an equivalent Jinja template. See `tests/parity/` for paired fixtures and the diff harness.
