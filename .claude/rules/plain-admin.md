---
paths:
  - "plain-admin/**/*.html"
  - "plain-admin/**/*.css"
  - "plain-admin/**/*.js"
  - "**/templates/admin/**/*.html"
---

# Admin UI

Admin styles are a per-component CSS layer with Plain's brand palette. Component CSS is wrapped in `@scope (.plain-admin)` so a user using `class="admin-card"` or `class="admin-btn"` on their own pages doesn't pick up admin styling.

**Where to look when customizing:**

- **`/admin/ui/`** — live catalog: copy-pasteable markup for every primitive, every design token rendered as a swatch with its current value, and the theming guide. Open this first.
- `uv run plain docs admin` — full theming and component reference
- `plain-admin/plain/admin/styles/` — source of truth (`tokens.css`, `components/*.css`)

## Use tokens, not hardcoded colors

The admin runs in light or dark mode via `.dark` on `<html>`. Always reference design tokens — never literal stone/black/white.

- Surfaces: `bg-admin-background`, `bg-admin-muted`, `bg-admin-card`, `bg-admin-popover` (paired `text-*-foreground`)
- Borders: `border-admin-border` (general), `border-admin-input` (form fields)
- Actions: `bg-admin-primary` / `text-admin-primary-foreground`, focus ring `ring-admin-ring`
- Status: `text-admin-success/warning/danger/info`; translucent backgrounds via `/10` (e.g. `bg-admin-warning/10`)
- Links: `text-admin-link hover:text-admin-link-hover`

## Components

Use the shipped classes — don't rebuild a primitive that already exists with raw Tailwind. Categories: buttons, form fields, surfaces (card/alert/badge/progress), overlays (dialog/popover/dropdown-menu/hovercard, plus tooltips via `data-tooltip`), switchers (tabs/segmented), inline (kbd/icon).

For variants, sizes, and copy-pasteable markup, see `/admin/ui/`.

## Elements

The admin ships Plain elements for forms and chrome. Common ones:
`<admin.Submit>`, `<admin.InputField>`, `<admin.SelectField>`, `<admin.CheckboxField>`, `<admin.TextareaField>`, `<admin.Icon name="…">`, `<admin.SearchInput>`. Use them instead of hand-writing `<button class="admin-btn admin-btn-primary">` or wiring up labels + errors yourself.

Templates that use elements must include `{% use_elements %}`. Source: `plain-admin/plain/admin/templates/elements/admin/`. Run `uv run plain docs admin --search elements` for the full table.

## Behaviors

Wire admin behaviors via the declarative `data-*` attributes from `assets/admin/behaviors.js` — don't bolt on inline handlers. The full list is at `/admin/ui/#behaviors`.
