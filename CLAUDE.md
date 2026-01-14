# Claude

## Commands and tools

- Open a Python shell: `uv run python`
- Run tests on all packages (or specify a package to test): `./scripts/test [package] [pytest options]`
- Lint and format code: `./scripts/fix`
- Make database migrations: `./scripts/makemigrations`

## Scratch directory

Use the `scratch` directory for one-off scripts, temporary files, and experimentation. This directory is gitignored. Write temporary files here instead of `/tmp`.

## Testing changes

The `example` directory contains a demo app with all Plain packages installed. You can `cd` into `example` and use `uv run plain`.

## READMEs

Each top-level package directory (e.g., `plain-api/`) has a `README.md` symlink pointing to the actual README inside the package (e.g., `plain-api/plain/api/README.md`). Only edit the README inside the package itself.

The README answers: "How do I use this?" It's not a complete API reference. It gets users productive quickly and points them to code for deeper exploration. See [`plain-jobs/plain/jobs/README.md`](plain-jobs/plain/jobs/README.md) as a good example.

### Structure

Every README should follow this order:

1. **h1** with package name
2. **Bold one-liner** describing the package in one sentence
3. **Table of contents** with links to h2s and h3s
4. **Overview** section with basic working examples
5. **Feature sections** as needed
6. **FAQs** section (second to last) using h4s for questions
7. **Installation** section (always last) - gets user from nothing to something working

### Style

- **Conversational tone**: "You can..." not "The module provides..."
- **First code example must be copy-paste ready** with imports included
- **Subsequent examples can be minimal**, building on what was shown
- **Link to source for advanced features**: `[ClassName](./file.py#ClassName)`
- **Cross-package references link to READMEs**: `[plain.auth](../../plain-auth/plain/auth/README.md)`

### What to document

- **If users import it, document it** - that's the bar for what needs docs
- **Mention all public features**, even advanced ones briefly, then link to code
- **Internal APIs stay undocumented** - `_prefix` functions and `@internalcode` decorated items are invisible to docs
- **Don't fully document every parameter** - mention the feature exists, link to code for details

## Type annotations

We are gradually adding type annotations to improve IDE/type checker friendliness. We are using Python 3.13+. Use the following workflow:

1. **Check current coverage**: `uv run plain code annotations <directory> --details`
2. **Add annotations**: Focus on function/method signatures (parameters and return types)
3. **Type check**: `./scripts/type-check <directory>` (uses `uv run ty check`)
4. **Format**: `./scripts/fix`
5. **Test**: `./scripts/test <package>`
6. **Verify improvement**: `uv run plain code annotations <directory>`
7. **Add to validation**: Once a directory reaches 100% coverage, add it to `FULLY_TYPED_PATHS` in `scripts/type-validate` to prevent regressions

Guidelines:

- Add `from __future__ import annotations` when necessary
- Focus on public APIs and user-facing methods first
- Don't annotate `__init__` return types (type checkers infer `None`)
- Use explicit `return None` for functions with `-> Type | None` return type
- Some Django-style ORM patterns are inherently difficult to type - that's okay
- Goal is progress, not perfection

Example workflow:

```bash
# Check coverage
uv run plain code annotations plain/plain/assets --details

# After adding annotations...
./scripts/type-check plain/plain/assets
./scripts/fix
./scripts/test plain
uv run plain code annotations plain/plain/assets  # Should show 100%
```

## Coding style

- Don't include args and returns in docstrings if they are already type annotated.
- CLI command docstrings should be concise, informative, no punctuation at the end.
- Don't use overloaded terms. Where possible, prefer unique, specific, and greppable names.

## Verifying changes

Not everything needs a test, but be liberal about using `print()` statements to verify changes and show the before and after effects of your changes. Make sure those print statements are removed before committing your changes.

## Documentation

When writing documentation (READMEs, docstrings, etc.), follow the principles from [What Makes Documentation Good](https://github.com/openai/openai-cookbook/blob/main/articles/what_makes_documentation_good.md):

- Make docs easy to skim
    - Split content into sections with titles.
    - Prefer titles with informative sentences over abstract nouns.
    - Include a table of contents.
    - Keep paragraphs short.
    - Begin paragraphs and sections with short topic sentences that give a standalone preview.
    - Put topic words at the beginning of topic sentences.
    - Put the takeaways up front.
    - Use bullets and tables.
    - Bold important text.
- Write well
    - Keep sentences simple.
    - Write sentences that can be parsed unambiguously.
    - Avoid left-branching sentences.
    - Avoid demonstrative pronouns (e.g., "this"), especially across sentences.
    - Be consistent.
    - Don't tell readers what they think or what to do.
- Be broadly helpful
    - Write simply.
    - Avoid abbreviations.
    - Offer solutions to potential problems.
    - Prefer terminology that is specific and accurate.
    - Keep code examples general and exportable.
    - Prioritize topics by value.
    - Don't teach bad habits.
    - Introduce topics with a broad opening.
- Break these rules when you have a good reason
    - "Documentation is an exercise in empathy."
