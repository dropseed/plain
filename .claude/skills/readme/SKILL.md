---
name: readme
description: Guidelines for writing and editing Plain package READMEs. Use this when creating or updating README files.
---

# README Guidelines

Each top-level package directory (e.g., `plain-api/`) has a `README.md` symlink pointing to the actual README inside the package (e.g., `plain-api/plain/api/README.md`). **Only edit the README inside the package itself.**

See [`plain-jobs/plain/jobs/README.md`](plain-jobs/plain/jobs/README.md) as a good example.

## Purpose

The README answers: "How do I use this?" It gets users productive quickly and points them to code for deeper exploration. It is not a complete API reference.

## Required Structure

Every README follows this order:

1. **h1** with package name
2. **Bold one-liner** describing the package
3. **Table of contents** with links to h2s and h3s
4. **Overview** section with basic working examples
5. **Feature sections** as needed
6. **FAQs** section (second to last) using h4s for questions
7. **Installation** section (always last)

## Style

- **Conversational tone**: "You can..." not "The module provides..."
- **First code example must be copy-paste ready** with imports included
- **Subsequent examples can be minimal**, building on what was shown
- **Link to source for advanced features**: `[ClassName](./file.py#ClassName)`
- **Cross-package references**: `[plain.auth](../../plain-auth/plain/auth/README.md)`

## What to Document

- **If users import it, document it**
- **Mention all public features**, even advanced ones briefly, then link to code
- **Internal APIs stay undocumented** (`_prefix` functions and `@internalcode`)
- **Don't fully document every parameter** - mention features exist, link to code

## Writing Tips

- Keep paragraphs short
- Put takeaways up front
- Use bullets and tables
- Bold important text
- Keep sentences simple and unambiguous
