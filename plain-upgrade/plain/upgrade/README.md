# plain.upgrade

**Upgrade Plain packages using AI agents.**

The `plain-upgrade` command can be run using `uvx` (part of the `uv` package manager) and will update the Plain packages in your project, then prompt an AI agent to run any additional upgrade steps for each package.

The recommended way to use it is to define your preferred LLM/AI agent command either in your personal shell configuration (ex. `.zshrc` or `.bashrc`) or in your project (ex. `.env`).

```bash
export PLAIN_UPGRADE_AGENT_COMMAND="codex --model o3 --flex-mode --auto-edit"
```

Updating Plain is then as simple as running:

```bash
uvx plain-upgrade
```

Note that this command only supports `uv` currently. Run `uvx plain-upgrade --help` for more options.
