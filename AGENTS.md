# Agents

This is the only AGENTS.md file in the repo -- you don't need to look for others.

## Commands and tools

- Open a Python shell: `uv run python`
- Run tests on all packages (or specify a package to test): `./scripts/test [package] [pytest options]`
- Lint and format code: `./scripts/fix`
- Make database migrations: `./scripts/makemigrations`

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

## Verifying changes

Not everything needs a test, but be liberal about using `print()` statements to verify changes and show the before and after effects of your changes. Make sure those print statements are removed before committing your changes.
