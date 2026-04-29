---
paths:
  - "plain-admin/**/*.html"
  - "plain-admin/**/*.css"
  - "plain-admin/**/*.js"
  - "**/templates/admin/**/*.html"
---

# Admin UI

The admin's UI is built on a per-component CSS layout derived from
[Basecoat UI](https://basecoatui.com) (MIT — see `styles/ATTRIBUTIONS.md`)
plus Plain's brand palette and admin-specific helpers.

```
plain-admin/plain/admin/
├── tailwind.css                          ← entry, auto-discovered by plain-tailwind
├── styles/                               ← build-time only (compiled into Tailwind)
│   ├── tokens.css                        ← variables (light + dark), @theme, @custom-variant
│   ├── base.css                          ← @layer base resets
│   ├── components/                       ← one file per UI primitive
│   │   ├── alert.css
│   │   ├── badge.css                     ← + Plain semantic variants
│   │   ├── button.css
│   │   ├── card.css
│   │   ├── dialog.css
│   │   ├── dropdown-menu.css
│   │   ├── input.css
│   │   ├── …
│   │   └── tooltip.css
│   ├── admin/                            ← admin-only chrome (not @scope-wrapped)
│   │   ├── code.css
│   │   └── nav.css
│   └── ATTRIBUTIONS.md                   ← MIT credit for Basecoat-derived code
└── assets/admin/
    ├── components/                       ← vanilla JS (registers via MutationObserver)
    │   ├── basecoat.js                   ← registry; exposes window.basecoat
    │   ├── dropdown-menu.js
    │   ├── popover.js
    │   ├── select.js
    │   ├── tabs.js
    │   └── toast.js
    ├── admin.js                          ← jQuery glue, HTMX hooks, dialog handlers
    ├── theme.js                          ← dark-mode toggle + persistence
    └── …
```

The component CSS files under `styles/components/` are wrapped in
`@scope (.plain-admin)` by `tailwind.css` so a user using `class="card"`
or `class="btn"` on their own pages doesn't pick up admin styling.

## Components

Use the component classes for UI primitives:

| Pattern        | Class                                                                        |
| -------------- | ---------------------------------------------------------------------------- |
| Buttons        | `btn`, `btn-primary`, `btn-outline`, `btn-ghost`, `btn-destructive`, ...     |
| Sizes / icons  | prefix with `btn-sm-`, `btn-lg-`, `btn-icon-`, etc.                          |
| Badges         | `badge`, `badge-secondary`, `badge-destructive`, `badge-outline`             |
| Plain semantic | `badge-success`, `badge-warning`, `badge-danger`, `badge-info`               |
| Cards          | `card` — pad with utilities (e.g. `card gap-2 py-4` for dense layouts)       |
| Form fields    | `input`, `textarea`; native `<select>` is auto-styled inside `.plain-admin`  |
| Dialogs        | `<dialog class="dialog">` + `data-dialog-open="..."` / `data-dialog-close`   |
| Dropdowns      | `.dropdown-menu` wrapping a `<button>` + `[data-popover]` w/ `[role="menu"]` |
| Tabs           | `.tabs > [role="tablist"] > [role="tab"]` (uses tabs.js)                     |

The live catalog is at `/admin/customization/` — copy-pasteable markup
for every primitive plus the design tokens and customization guide.

## Tokens (don't hardcode colors)

The admin runs in light or dark mode based on the `.dark` class on `<html>`.
Templates and CSS should reference design tokens, not stone/black/white.

| Use                 | Token / class                                              |
| ------------------- | ---------------------------------------------------------- |
| Page background     | `bg-background`                                            |
| Body text           | `text-foreground`                                          |
| Secondary text      | `text-muted-foreground`                                    |
| Subtle surfaces     | `bg-muted`, `bg-muted/40`                                  |
| Hover surface       | `hover:bg-accent` (`hover:text-accent-foreground`)         |
| Borders             | `border-border` (general), `border-input` (fields)         |
| Focus ring          | `ring-ring`                                                |
| Popover/dropdown bg | `bg-popover` / `text-popover-foreground`                   |
| Primary action      | `bg-primary` / `text-primary-foreground`                   |
| Link                | `text-link hover:text-link-hover`                          |
| Destructive action  | `bg-destructive` / `text-white`                            |
| Status colors       | `text-success`, `text-warning`, `text-danger`, `text-info` |

For status backgrounds at lower opacity (badges, alerts), use the
opacity modifier on the same token: `bg-success/10`, `bg-warning/10`.

## CSP

Same rules as the rest of the admin: no inline `style=`, no inline `<script>`
without a `nonce`, no inline event handlers (`onclick=`, ...). Wire JS via
`data-*` attributes and listeners in `admin.js`.

For dialogs, use the existing helper — never write `onclick="dialog.showModal()"`:

```html
<button type="button" data-dialog-open="my-dialog" class="btn-primary">Open</button>
<dialog id="my-dialog" class="dialog">
  <article>
    <header><h2>Title</h2></header>
    <section>Body</section>
    <footer>
      <button data-dialog-close="my-dialog" class="btn-outline">Close</button>
    </footer>
  </article>
</dialog>
```

## Adding a new component

1. Create `styles/components/<name>.css` with a single `@layer components { ... }` block.
2. Add `@import "./styles/components/<name>.css";` inside the `@scope (.plain-admin) { ... }` block in `tailwind.css`.
3. If the component needs JS, drop a vanilla module in `assets/admin/components/<name>.js` and `<script>` it from `base.html`.
4. Document it on `/admin/customization/`.

Run `uv run plain docs admin --section components` for the full list and
`uv run plain docs admin --section customization` for theming details.
