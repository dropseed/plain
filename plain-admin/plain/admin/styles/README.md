# Admin styles

The admin's CSS, organized as a per-component system. Compiled into the
user's Tailwind v4 build via `../tailwind.css`, which is auto-discovered
by the [`plain.tailwind`](../../../../plain-tailwind/plain/tailwind/README.md)
package — these files are not served to the browser directly.

## Layout

| File               | What's inside                                                                                                     |
| ------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `tokens.css`       | Design tokens (light + dark) on `.plain-admin` and `.dark .plain-admin`, plus the Tailwind `@theme` bindings.     |
| `base.css`         | `@layer base` resets and element defaults (tables, native form fields, prose links).                              |
| `components/*.css` | One file per UI primitive. Each is a single `@layer components { ... }` block with `@apply`-based Tailwind rules. |
| `admin/*.css`      | Admin-only chrome that lives outside `@scope (.plain-admin)` (e.g. `nav.css` for the pinned-tab drag-and-drop).   |
| `ATTRIBUTIONS.md`  | MIT license preservation for the Basecoat-derived parts.                                                          |

## How scoping works

`tailwind.css` wraps every `components/*.css` import in `@scope (.plain-admin)`
so a user using `class="card"` or `class="btn"` on their own (non-admin)
pages doesn't accidentally pick up admin styling. The token vars in
`tokens.css` are also declared on `.plain-admin` (not `:root`) for the
same reason — outside the admin chrome the variables are undefined and
utilities like `bg-primary` render no color.

`@scope` is supported in Chrome 118+, Safari 17.4+, Firefox 128+ — fine
for an admin-only context.

## Adding a component

1. Drop `components/<name>.css` with a single `@layer components { ... }` block.
2. Add `@import "./styles/components/<name>.css";` inside the `@scope (.plain-admin) { ... }` block in `../tailwind.css`.
3. If the component needs JS, add a vanilla module in
   `../assets/admin/components/<name>.js` and `<script>` it from
   `../templates/admin/base.html`.
4. Add a section to the live catalog at `/admin/customization/`
   (`../templates/admin/customization.html`).

## Customizing without forking

Override any `--token` from `tokens.css` in your own stylesheet loaded
after `tailwind.min.css`. For example, to change the primary action color:

```css
.plain-admin {
  --primary: #4f46e5;
  --primary-foreground: white;
  --ring: #4f46e5;
}
.dark .plain-admin {
  --primary: #818cf8;
  --primary-foreground: #1e1b4b;
}
```

Every `.btn-primary`, focus ring, and link color in the admin will pick
that up — no template changes required.
