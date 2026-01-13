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

Inside each top level subdirectory is a `README.md` that is a symlink to the `README.md` in the of the Python package itself. You only need to edit the `README.md` inside of the package itself.

The README is the main written documentation for the package (or module). You can structure it using [`plain-api/plain/api/README.md`](/plain/plain/assets/README.md) as an example.

Some instructions for writing READMEs:

- Underneath the h1 should be a **<short description>** (in bold) that describes the package in one sentence.
- There should be a table of contents at the top with links to the h2s and h3s in the README.
- When referencing specific classes or functions in code, link to them with a # fragment identifier, like this: [`AssetView`](./views.py#AssetView).
- The first section of the README should be an **Overview** that gets straight into basic examples of how to use the package.
- An **Installation** section should always be present but it should be the last section of the README.
- The **Installation** section should get the user from nothing to _something_, even if _something_ is a demo/example view or code that will need additional customization.
- The **Installation** steps will typically be run by an agent like Claude Code, but they also need to be written in a way that a human can follow them.
- Miscellaneous notes or information about the package should be added as **FAQs** in the second to last section of the README.
- For the **FAQs**, use h4s for the questions.
- The most advanced usages of the package don't need to be fully documented (i.e. every possible paramater, etc.). They can be mentioned if the user otherwise wouldn't know about them, but then they can be linked to the code itself for more information.

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
