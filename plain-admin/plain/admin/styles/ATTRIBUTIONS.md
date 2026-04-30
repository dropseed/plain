# Third-party attributions

Plain's admin component styles started life as a fork of
[Basecoat UI](https://basecoatui.com) (MIT) by Ronan Berder. The
component class names, the shadcn-flavored token palette in
`tokens.css`, and the `@apply`-based component rules under `components/`
all derive from that work.

Basecoat's MIT license is preserved in full below as required by the
license. The original upstream is at <https://github.com/hunvreus/basecoat>.

The vendored JavaScript component modules under
`../assets/admin/components/` are also derived from Basecoat (vanilla JS,
also MIT) and carry the original copyright header at the top of each
file.

## Fonts

The admin's default `--font-sans` and `--font-mono` stacks lead with two
vendored typefaces, both licensed under the SIL Open Font License 1.1:

- **Inter** by Rasmus Andersson — `../assets/admin/fonts/InterVariable.woff2`
  and `InterVariable-Italic.woff2`. License at
  `../assets/admin/fonts/Inter-OFL.txt`. Upstream:
  <https://github.com/rsms/inter>.
- **JetBrains Mono** by JetBrains — `../assets/admin/fonts/JetBrainsMono.woff2`.
  License at `../assets/admin/fonts/JetBrainsMono-OFL.txt`. Upstream:
  <https://github.com/JetBrains/JetBrainsMono>.

System font stacks remain as fallbacks. To opt out, override `--font-sans`
or `--font-mono` in your own theme.

---

MIT License

Copyright (c) 2025 Ronan Berder

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
