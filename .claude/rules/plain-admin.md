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
│   │   ├── nav.css
│   │   └── prose.css
│   └── ATTRIBUTIONS.md                   ← MIT credit for Basecoat-derived code
└── assets/admin/
    ├── components.js                     ← popover, dropdown-menu, hovercard, tabs
    │                                       (init on DOMContentLoaded + htmx:afterSwap)
    ├── behaviors.js                      ← declarative data-* handlers
    │                                       (data-column-autolink, data-autosubmit,
    │                                       data-copy-value, data-encrypted)
    ├── htmx.js                           ← HTMX network-error alerts
    ├── theme.js                          ← dark-mode toggle + persistence
    └── …
```

The component CSS files under `styles/components/` are wrapped in
`@scope (.plain-admin)` by `tailwind.css` so a user using `class="card"`
or `class="btn"` on their own pages doesn't pick up admin styling.

## Components

Use the component classes for UI primitives:

| Pattern        | Class                                                                              |
| -------------- | ---------------------------------------------------------------------------------- |
| Buttons        | `btn`, `btn-primary`, `btn-outline`, `btn-ghost`, `btn-link`                       |
| Sizes / icons  | prefix with `btn-sm-`, `btn-lg-`, `btn-icon-`, etc.                                |
| Status buttons | `btn-success`, `btn-warning`, `btn-danger`, `btn-info` (solid; paired fg)          |
| Badges         | `badge`, `badge-secondary`, `badge-outline`                                        |
| Status badges  | `badge-success`, `badge-warning`, `badge-danger`, `badge-info` (translucent)       |
| Alerts         | `alert`, `alert-success`, `alert-warning`, `alert-danger`, `alert-info`            |
| Progress       | `<progress class="progress">` — `data-status="warning"` / `"error"` for fill color |
| Cards          | `card` — pad with utilities (e.g. `card gap-2 py-4` for dense layouts)             |
| Form fields    | `input`, `textarea`, `select` — opt in via class; pair with `-sm` for compact rows |
| Dialogs        | `<dialog class="dialog">` + `<button command="show-modal" commandfor="<id>">`      |
| Dropdowns      | `.dropdown-menu` wrapping a `<button>` + `[data-popover]` w/ `[role="menu"]`       |
| Tabs           | `.tabs > [role="tablist"] > [role="tab"]` (uses tabs.js)                           |
| Hovercards     | `<span class="hovercard">` + trigger + `<div data-hovercard aria-hidden="true">`   |
| Kbd            | `<kbd class="kbd">Esc</kbd>` — inline key-name pill                                |

The live catalog is at `/admin/customization/` — copy-pasteable markup
for every primitive plus the design tokens and customization guide.

## Behaviors

Declarative `data-*` attributes you sprinkle on existing elements. No CSS, no markup pattern — delegated handlers live in `assets/admin/behaviors.js`.

| Attribute                      | What it does                                                                |
| ------------------------------ | --------------------------------------------------------------------------- |
| `data-copy-value="…"`          | Click writes value to clipboard; optional `[data-copy-feedback]` text swap. |
| `data-autosubmit`              | On a form field — submit the enclosing form on `change`.                    |
| `data-column-autolink="<url>"` | Wrap a table cell's content in an `<a href>` link.                          |
| `data-encrypted="<value>"`     | Click to reveal/hide an encrypted value (API keys, etc.).                   |

GET-form submissions are also globally intercepted to drop empty params from the URL — applies to every `<form method="GET">`, no attribute needed.

## Tokens (don't hardcode colors)

The admin runs in light or dark mode based on the `.dark` class on `<html>`.
Templates and CSS should reference design tokens, not stone/black/white.

| Use                 | Token / class                                                 |
| ------------------- | ------------------------------------------------------------- |
| Page background     | `bg-background`                                               |
| Body text           | `text-foreground`                                             |
| Secondary text      | `text-muted-foreground`                                       |
| Subtle surfaces     | `bg-muted`, `bg-muted/40`                                     |
| Hover surface       | `hover:bg-accent` (`hover:text-accent-foreground`)            |
| Borders             | `border-border` (general), `border-input` (fields)            |
| Focus ring          | `ring-ring`                                                   |
| Popover/dropdown bg | `bg-popover` / `text-popover-foreground`                      |
| Primary action      | `bg-primary` / `text-primary-foreground`                      |
| Link                | `text-link hover:text-link-hover`                             |
| Status actions      | `bg-{success,warning,danger,info}` / `text-{name}-foreground` |
| Status text         | `text-success`, `text-warning`, `text-danger`, `text-info`    |

For status backgrounds at lower opacity (badges, alerts), use the
opacity modifier on the same token: `bg-success/10`, `bg-warning/10`.

## CSP

Same rules as the rest of the admin: no inline `style=`, no inline `<script>`
without a `nonce`, no inline event handlers (`onclick=`, ...). Wire JS via
delegated handlers in `assets/admin/behaviors.js` (or native HTML where it
exists — see dialogs).

For dialogs, use the native HTML Invoker Commands API — never write
`onclick="dialog.showModal()"`:

```html
<button type="button" command="show-modal" commandfor="my-dialog" class="btn-primary">Open</button>
<dialog id="my-dialog" class="dialog">
  <article>
    <header><h2>Title</h2></header>
    <section>Body</section>
    <footer>
      <button command="close" commandfor="my-dialog" class="btn-outline">Close</button>
    </footer>
  </article>
</dialog>
```

Closing from inside without an id also works via
`<form method="dialog"><button>…</button></form>` — submitting that form
closes the enclosing dialog and returns the button's `value`.

## Adding a new component

1. Create `styles/components/<name>.css` with a single `@layer components { ... }` block.
2. Add `@import "./styles/components/<name>.css";` inside the `@scope (.plain-admin) { ... }` block in `tailwind.css`.
3. If the component needs JS, add an init block to `assets/admin/components.js` (one delegated handler per primitive — no per-instance listeners; outside-click is shared).
4. Document it on `/admin/customization/`.

Run `uv run plain docs admin --section components` for the full list and
`uv run plain docs admin --section customization` for theming details.
