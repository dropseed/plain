---
paths:
  - "plain-admin/**/*.html"
  - "plain-admin/**/*.css"
  - "plain-admin/**/*.js"
  - "**/templates/admin/**/*.html"
---

# Admin UI

Admin styles are a per-component CSS layer with Plain's brand palette. Component CSS is wrapped in `@scope (.plain-admin)` so a user using `class="card"` or `class="btn"` on their own pages doesn't pick up admin styling.

**Where to look when customizing:**

- **`/admin/ui/`** — live catalog: copy-pasteable markup for every primitive, every design token rendered as a swatch with its current value, and the theming guide. Open this first.
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

Use the shipped classes — don't rebuild a primitive that already exists with raw Tailwind. Categories: buttons, form fields, surfaces (card/alert/badge/progress), overlays (dialog/popover/dropdown-menu/hovercard, plus tooltips via `data-tooltip`), switchers (tabs/segmented), inline (kbd/icon).

For variants, sizes, and copy-pasteable markup, see `/admin/ui/`.

## Behaviors

Wire admin behaviors via the declarative `data-*` attributes from `assets/admin/behaviors.js` — don't bolt on inline handlers. The full list is at `/admin/ui/#behaviors`.
