# plain.skills

**Agent skills for working with Plain projects.**

These skills provide context and workflows for common tasks when using [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [Codex](https://codex.openai.com/).

## Available skills

| Skill              | Description                                                    |
| ------------------ | -------------------------------------------------------------- |
| `plain-docs`       | Retrieves detailed documentation for Plain packages            |
| `plain-install`    | Installs Plain packages and guides through setup steps         |
| `plain-upgrade`    | Upgrades Plain packages and applies required migration changes |
| `plain-shell`      | Runs Python with Plain configured and database access          |
| `plain-request`    | Makes test HTTP requests against the development database      |
| `plain-principles` | Provides Plain framework context and coding conventions        |

## Installation

To install skills to your project's `.claude/` or `.codex/` directory:

```bash
uv run plain skills --install
```

This copies the skill definitions so your agent can use them. Run it again after upgrading Plain to get updated skills.
