# Agent guidance

Plain is a web framework forked from Django, but its APIs have diverged — don't assume Django patterns apply. When reviewing, flag code that reintroduces Django-isms (`request.GET`/`request.POST`, `urlpatterns`, Django-style middleware) instead of Plain equivalents (`request.query_params`/`request.form_data`, `Router` with `urls`, `before_request`/`after_response`).

Fuller conventions live in `CLAUDE.md` at the repo root — treat it as the source of truth for coding style, testing, and CSP rules.

## Code review rules

- **Formatting/linting**: enforced by `./scripts/fix` in CI — don't flag style that tooling already covers.
- **Tests**: `<package>/tests/public/` is the user-facing contract; `<package>/tests/internal/` is regenerable change-detection. New user-visible behavior should have a public test.
- **CSP-safe templates/assets**: no inline `style="..."` attributes, no inline event handlers (`onclick=`), inline `<style>`/`<script>` tags need `nonce="{{ request.csp_nonce }}"`.
- **Settings**: never `getattr(settings, "X", default)` — all known settings have registered defaults, so `settings.X` is always safe.
- **Logging**: no f-strings or `%` formatting in log messages — variable data goes in `context={}`.
- **Backwards compatibility**: API renames/signature changes are fine (upgrades are agent-assisted); don't flag them. Deeper breaking changes users can't fix in their own code still deserve scrutiny.
- Python 3.13+ — modern syntax (`X | Y` unions, `match`) is expected, not a finding.
