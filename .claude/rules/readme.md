---
paths:
  - "**/README.md"
---

# README Guidelines

Edit the README inside the package (e.g., `plain-api/plain/api/README.md`), not the top-level symlink.

See `plain-jobs/plain/jobs/README.md` as a good example.

## Required structure (in order)

1. h1 with package name
2. Bold one-liner describing the package
3. Table of contents linking to h2s and h3s
4. Overview section with basic working examples
5. Feature sections as needed
6. FAQs section (second to last) using h4s for questions
7. Installation section (always last)

## Style

- Conversational tone: "You can..." not "The module provides..."
- First code example must be copy-paste ready with imports
- Subsequent examples can be minimal, building on what was shown
- Link to source for advanced features: `[ClassName](./file.py#ClassName)`
- Cross-package references: `[plain.auth](../../plain-auth/plain/auth/README.md)`

## What to document

- If users import it, document it
- Mention all public features, even advanced ones briefly, then link to code
- Internal APIs stay undocumented (`_prefix` functions and `@internalcode`)
- Don't fully document every parameter — mention features exist, link to code

## Writing tips

- Keep paragraphs short, put takeaways up front
- Use bullets and tables, bold important text
- Keep sentences simple and unambiguous
