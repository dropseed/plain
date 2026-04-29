# Basecoat (vendored)

This directory contains a vendored copy of [Basecoat UI](https://basecoatui.com)
— a Tailwind-CSS-based component library that ports the [shadcn/ui](https://ui.shadcn.com)
visual language to plain HTML, no React required.

The Plain admin uses Basecoat as its component foundation. Basecoat is
distributed under the MIT license; the original `LICENSE.md` is preserved here
unchanged.

## Layout

- `basecoat.css` — the upstream stylesheet, vendored verbatim. The only
  modification is a vendor-attribution header comment. Component rules (button,
  card, badge, dialog, dropdown-menu, etc.) live here as `@layer components`
  with `@apply`-based Tailwind v4 utilities.
- `js/` — upstream JavaScript modules (vanilla, no framework dependency). Each
  registers itself with `basecoat.js` and initializes via `MutationObserver`
  so it works with HTMX swaps. Modules are independent — include only the ones
  you use.
- `LICENSE.md` — Basecoat's MIT license.

## Plain customization

Plain-specific design tokens (the olive/steel palette, semantic colors) are
declared in `../admin.css`, which is loaded **after** `basecoat.css`. That file
overrides Basecoat's `--primary`, `--secondary`, `--destructive`, etc. with
Plain's brand palette, and provides the dark-mode variants. The rules in this
directory should not be edited directly — change `admin.css` instead so the
upstream diff stays small and updates remain mechanical.

## Updating

```sh
# from this directory
curl -O https://raw.githubusercontent.com/hunvreus/basecoat/main/src/css/basecoat.css
curl -O https://raw.githubusercontent.com/hunvreus/basecoat/main/LICENSE.md
for f in basecoat command dropdown-menu popover select sidebar tabs toast; do
  curl -o js/$f.js "https://raw.githubusercontent.com/hunvreus/basecoat/main/src/js/$f.js"
done
```

After updating, re-add the vendor header at the top of `basecoat.css` and
verify the `:root` token names in this file match the overrides in
`../admin.css`.
