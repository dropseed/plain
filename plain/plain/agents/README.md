# plain.agents

**Sync AI agent rules and skills from installed Plain packages into your project.**

- [Overview](#overview)
- [Installing agent context](#installing-agent-context)
- [Listing available skills](#listing-available-skills)
- [How packages ship agent content](#how-packages-ship-agent-content)
    - [Directory structure](#directory-structure)
    - [Rules](#rules)
    - [Skills](#skills)
- [Creating rules for your package](#creating-rules-for-your-package)
- [Creating skills for your package](#creating-skills-for-your-package)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain packages ship rules and skills that give AI coding assistants context about how to use them. Rules are concise guardrails loaded automatically, and skills are multi-step workflows invoked via `/slash-commands`.

Running `plain agent install` copies these files from your installed packages into your project's `.claude/` directory, where your AI assistant can use them.

```bash
$ plain agent install
Agent: installed 5 in .claude/
```

This is the recommended way to keep your AI assistant up to date with the Plain packages you have installed.

## Installing agent context

Run [`plain agent install`](../cli/agent.py#install) to sync rules and skills from all installed `plain.*` and `plainx.*` packages into your project's `.claude/` directory.

```bash
$ plain agent install
```

The command:

- **Copies rules** (`.md` files) into `.claude/rules/`
- **Copies skills** (directories with `SKILL.md`) into `.claude/skills/`
- **Skips unchanged files** by comparing modification times, so repeated runs are fast
- **Removes orphans** — if you uninstall a package, its rules and skills are cleaned up automatically

Only items prefixed with `plain` or `plainx` are managed. Your own custom rules and skills are never touched.

Run this after installing or upgrading Plain packages to keep your agent context current.

## Listing available skills

Use [`plain agent skills`](../cli/agent.py#skills) to see what skills are available from your installed packages:

```bash
$ plain agent skills
Available skills:
  - plain-install
  - plain-optimize
  - plain-upgrade
```

These skills become available as `/slash-commands` in your AI assistant after running `plain agent install`.

## How packages ship agent content

### Directory structure

Packages include an `agents/.claude/` directory alongside their Python code:

```
plain-jobs/
  plain/
    jobs/
      agents/
        .claude/
          rules/
            plain-jobs.md
          skills/
            plain-some-skill/
              SKILL.md
      __init__.py
      models.py
      ...
```

### Rules

Rules are `.md` files in `agents/.claude/rules/`. They provide concise guardrails — short bullet-point reminders, not full tutorials. Rules support optional `paths:` frontmatter to scope them to specific files:

```markdown
---
paths:
  - "**/jobs.py"
---

# Background Jobs

## Best Practices

### Keep jobs idempotent

Jobs may retry on failure. Design them so re-execution is safe.
```

When `paths:` is set, the rule only loads when the AI assistant is working on matching files.

### Skills

Skills are directories containing a `SKILL.md` file in `agents/.claude/skills/`. The `SKILL.md` uses frontmatter to define the skill's name and description:

```markdown
---
name: plain-install
description: Installs Plain packages and guides through setup steps.
---

# Install Plain Packages

## 1. Install the package(s)
...
```

The `name` becomes the `/slash-command` and the `description` tells the AI assistant when to invoke it.

## Creating rules for your package

Put rules in `<your-package>/agents/.claude/rules/<name>.md`. Keep them short (~50 lines) — they're loaded into context automatically, so every line costs attention.

**Guidelines:**

- Use bullet points, not paragraphs
- Show brief good/bad code examples for common mistakes
- Point to docs for full details: `Run \`uv run plain docs <pkg> --section X\` for full patterns`
- Use `paths:` frontmatter to scope rules to relevant file patterns (e.g., `"**/models.py"`)
- Prefix the filename with `plain-` or `plainx-` so `plain agent install` can manage it

## Creating skills for your package

Put skills in `<your-package>/agents/.claude/skills/<skill-name>/SKILL.md`. Skills are multi-step workflows — they coordinate tools, run commands, and guide multi-turn processes.

**SKILL.md format:**

```markdown
---
name: my-skill-name
description: One-line description of when to use this skill.
---

# Skill Title

## 1. First step
...

## 2. Second step
...

## Guidelines
- Constraints and rules for the workflow
```

**Guidelines:**

- Design for workflows, not reference docs — numbered steps the AI can follow
- Include any commands the skill should run
- Add a "Guidelines" section with constraints (e.g., "DO NOT commit changes")
- Prefix the skill name with `plain-` or `plainx-`

## FAQs

#### Do I need to run install after every package update?

Yes. Run `plain agent install` after installing or upgrading Plain packages. The command is fast — it skips files that haven't changed.

#### Will install delete my custom rules or skills?

No. Only files prefixed with `plain` or `plainx` are managed. Your own rules and skills are left untouched.

#### Where do the files end up?

Rules go to `.claude/rules/` and skills go to `.claude/skills/` in your project root. These are the standard locations that AI assistants look for context.

#### What packages are scanned?

All installed `plain.*` and `plainx.*` packages that contain an `agents/.claude/` directory.

## Installation

Agent commands are included with Plain. No additional installation is required. Just make sure your project has a `.claude/` directory.
