---
paths:
  - "plain-admin/**/*.html"
  - "plain-admin/**/*.css"
  - "plain-admin/**/*.js"
  - "**/templates/admin/**/*.html"
---

# Admin UI

The admin's UI is built on a vendored copy of [Basecoat UI](https://basecoatui.com)
(MIT) plus Plain's brand palette and a few admin-specific helpers.

```
plain-admin/plain/admin/assets/admin/
├── basecoat/
│   ├── basecoat.css      ← vendored verbatim (DO NOT EDIT)
│   ├── js/*.js           ← vanilla JS modules (DO NOT EDIT)
│   └── LICENSE.md        ← preserved from upstream
├── admin.css             ← Plain palette + admin-only chrome (edit this)
├── admin.js              ← Tippy dropdowns, HTMX glue, dialog handlers
└── theme.js              ← dark-mode toggle + persistence
```

## Components

Use Basecoat classes for UI primitives:

| Pattern        | Class                                                                       |
| -------------- | --------------------------------------------------------------------------- |
| Buttons        | `btn`, `btn-primary`, `btn-outline`, `btn-ghost`, `btn-destructive`, ...    |
| Sizes / icons  | prefix with `btn-sm-`, `btn-lg-`, `btn-icon-`, etc.                         |
| Badges         | `badge`, `badge-secondary`, `badge-destructive`, `badge-outline`            |
| Plain semantic | `badge-success`, `badge-warning`, `badge-danger`, `badge-info`              |
| Cards          | `card` (basecoat) or `admin-card` (Plain's denser metric card)              |
| Form fields    | `input`, `textarea`; native `<select>` is auto-styled inside `.plain-admin` |
| Dialogs        | `<dialog class="dialog">` + `data-dialog-open="..."` / `data-dialog-close`  |
| Tabs           | `.tabs > [role="tablist"] > [role="tab"]` (basecoat tabs.js)                |

The full live catalog is at `/admin/components/` — copy-pasteable markup for
every primitive plus the customization guide.

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
| Brand primary       | `bg-primary` / `text-primary-foreground` (= olive)         |
| Brand link          | `var(--plain-steel)` via `.plain-link`                     |
| Status colors       | `text-success`, `text-warning`, `text-danger`, `text-info` |

If a color isn't expressible in tokens (e.g. a one-off chart color), prefer
a Plain palette variable: `bg-[var(--plain-warning)]`.

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

## Updating Basecoat

`basecoat/` is vendored verbatim. To pull a newer version, follow the
instructions in `basecoat/README.md`. Keep customizations in `admin.css`
so the upstream diff stays mechanical.

Run `uv run plain docs admin --section components` for the full list and
`uv run plain docs admin --section customization` for theming details.
