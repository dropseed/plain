---
paths:
  - "plain-admin/**/*.html"
  - "plain-admin/**/*.css"
  - "plain-admin/**/*.js"
  - "**/templates/admin/**/*.html"
---

# Admin UI

Admin styles are derived from [Basecoat UI](https://basecoatui.com) plus Plain's brand palette. Component CSS is wrapped in `@scope (.plain-admin)` so a user using `class="card"` or `class="btn"` on their own pages doesn't pick up admin styling.

**Where to look when customizing:**

- **`/admin/customization/`** — live catalog: copy-pasteable markup for every primitive, every design token rendered as a swatch with its current value, and the theming guide. Open this first.
- `uv run plain docs admin --section customization` — written theming guide
- `uv run plain docs admin --section components` — full component reference
- `plain-admin/plain/admin/styles/` — source of truth (`tokens.css`, `components/*.css`)

## Use tokens, not hardcoded colors

The admin runs in light or dark mode via `.dark` on `<html>`. Always reference design tokens — never literal stone/black/white.

- Surfaces: `bg-background`, `bg-muted`, `bg-card`, `bg-popover` (paired `text-*-foreground`)
- Borders: `border-border` (general), `border-input` (form fields)
- Actions: `bg-primary` / `text-primary-foreground`, focus ring `ring-ring`
- Status: `text-success/warning/danger/info`; translucent backgrounds via `/10` (e.g. `bg-warning/10`)
- Links: `text-link hover:text-link-hover`

## Components

Use the shipped component classes — don't rebuild a primitive that already exists with raw Tailwind.

- **Buttons** `btn-{primary,secondary,outline,ghost,link,success,warning,danger,info}`; size with `btn-sm-*` / `btn-lg-*`; icon-only with `btn-icon-*`
- **Form fields** `.input`, `.textarea`, `.select`; compact rows with `input-sm` / `select-sm`; wrap label+control+errors in `.field` (group under `.fieldset`)
- **Surfaces** `.card`, `.alert{,-success,-warning,-danger,-info}`, `.badge{,-secondary,-outline,-success,-warning,-danger,-info}`, `<progress class="progress">`
- **Overlays** `.dialog`, `.popover`, `.dropdown-menu`, `.hovercard`; tooltips via `data-tooltip="…"`
- **Switchers** `.tabs` (content-panel switching, role=tablist), `.segmented` (mutually-exclusive value selection, role=radiogroup)
- **Inline** `.kbd`, `admin.Icon`

For exact markup, variants, and live previews, see `/admin/customization/`.

## Behaviors

Declarative `data-*` attributes wired in `assets/admin/behaviors.js`:

| Attribute                      | What it does                                              |
| ------------------------------ | --------------------------------------------------------- |
| `data-copy-value="…"`          | Click writes value to clipboard.                          |
| `data-autosubmit`              | On a form field — submit the enclosing form on `change`.  |
| `data-column-autolink="<url>"` | Wrap a table cell's content in an `<a href>` link.        |
| `data-encrypted="<value>"`     | Click to reveal/hide an encrypted value (API keys, etc.). |

GET-form submissions are also globally intercepted to drop empty params from the URL — no attribute needed.

## CSP

The admin runs under a strict CSP — these are non-negotiable:

- No inline `style="..."` attributes; toggle classes (`classList.add/remove`) instead.
- No inline `<script>` or `<style>` without `nonce="{{ request.csp_nonce }}"`.
- No inline event handlers (`onclick=`, `onload=`, …) — wire via delegated handlers in `assets/admin/behaviors.js` or `components.js`.
- For dialogs, use the native HTML Invoker Commands API: `<button command="show-modal" commandfor="my-dialog">` — never `onclick="dialog.showModal()"`.
