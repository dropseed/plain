# Plain Future Channel

If a project's `pyproject.toml` has `[tool.uv.sources]` entries with `git = "https://github.com/dropseed/plain"`, the project is opted into Plain's **future channel** — rolling unstable releases pulled from a github branch.

- Use the `/plain-future` skill to advance the channel (`plain future upgrade`) and apply upgrade instructions.
- Do **not** use the standard `/plain-upgrade` skill on a project that's on the future channel — `plain upgrade`'s PyPI version-bump flow doesn't apply to git-source packages, and `plain changelog` can't slice between commit SHAs.
- The user opted in deliberately. Don't suggest `plain future disable` unless they specifically ask to leave the channel.
- Breaking changes between syncs are expected. When `plain future upgrade` shows upgrade instructions, apply them.
