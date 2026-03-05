# plain: Agent Harness Improvements

Ideas from OpenAI's "Harness Engineering" article (Feb 2026) about making codebases more agent-friendly. Mapped to what Plain already does and where there's opportunity.

## Custom linters with remediation messages

Write lint rules whose error messages ARE the fix instructions. When an agent (or user's agent) violates a pattern, the error output tells it exactly what to do.

- Catch `Model.objects.` → "Use `Model.query` instead — see `uv run plain docs models --section querying`"
- Catch `from plain.models.fields import` → "Import from `plain.models.types` instead"
- Catch `{% csrf_token %}` in templates → "Plain uses automatic header-based CSRF. Remove this tag."
- Catch `class Meta:` in models → "Use `model_options = models.Options(...)` instead"
- Catch `unique=True` on fields → "Use `UniqueConstraint` in constraints instead"

The "Key Differences from Django" section in `plain.md` is the source list for these rules. Mechanical enforcement > documentation.

## Generated reference artifacts

`plain docs <pkg> --api` already generates API surfaces dynamically. Consider additional generated references that agents could consult:

- URL route map (`plain routes` or similar)
- Model relationship graph
- Middleware stack dump
- Installed packages and their versions

These help agents reason about the full system without reading every file.

## Agent-verifiable acceptance criteria

`plain request /path` already supports `--status`, `--contains`, `--not-contains`. Lean into this:

- Document patterns for agents to self-verify: "after modifying a view, run `plain request /that-path --status 200`"
- Consider richer assertion options (JSON path matching, header checks)
- Make `plain observer` traces easy to query from CLI for performance assertions

## Recurring drift detection

Agents replicate existing patterns — including bad ones. Rather than manual cleanup, run periodic scans:

- Inconsistent patterns across packages (different approaches to `__all__` exports, etc.)
- Rules/docs that have drifted from actual code behavior
- Stale examples in READMEs that don't match current APIs

Could be a skill or a script that opens targeted fix PRs.

## What Plain already does well

The three-tier system (rules → docs → skills) matches the article's core recommendation: "give the agent a map, not a 1,000-page manual." Rules are the table of contents (~50 lines), docs are progressive disclosure (on-demand via CLI), skills are executable workflows. This is the right architecture.
