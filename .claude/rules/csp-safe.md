---
paths:
  - "**/*.html"
  - "**/*.js"
  - "**/*.css"
---

# CSP-safe by default (this repo's templates and assets)

This is an internal stance for code we ship in Plain itself — packages, the admin, the toolbar, the example app. User projects pick their own CSP and are free to relax it; our shipped templates and assets must work under a strict policy.

- **No inline `style="..."` attributes in our HTML templates.** Use Tailwind utility classes; for one-offs use Tailwind arbitrary values (`h-[400px]`, `bg-[#abcdef]`).
- **Prefer classes/`data-*` over `el.style` in our JS.** For discrete state, toggle classes or data attributes (`classList.add/remove`, `el.dataset.x = ...`) — declarative and diff-friendly. CSP does _not_ block CSSOM property setters (`el.style.transform = ...`, `el.style.setProperty(...)`), so they're acceptable for genuinely dynamic, continuous values a class can't express (a drag position, a drag-resize dimension). CSP _does_ block `style="..."` attributes, `el.style.cssText = ...`, and `el.setAttribute("style", ...)` — never use those. Tailwind v4's `!` suffix (`hidden!`) provides `!important` when needed to defeat library-internal inline styles.
- **Inline `<style>` and `<script>` tags must carry `nonce="{{ request.csp_nonce }}"`.**
- **No inline event handlers** (`onclick=`, `onload=`, etc.). Wire behavior in the relevant JS file.
- For dialogs, use the native HTML Invoker Commands API: `<button command="show-modal" commandfor="my-dialog">` — never `onclick="dialog.showModal()"`.
- For dynamic SVG colors, use the `fill=`/`stroke=` presentation attributes — those aren't covered by `style-src`.

The `example/` app runs the strict CSP — exercise admin/toolbar/template changes there before shipping. Library-internal violations from third-party deps (e.g. Chart.js setting canvas inline styles) are a known cost; don't add to them on our side.
