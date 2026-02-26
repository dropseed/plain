---
name: plain-bug
description: Submit a bug report for the Plain framework. Use when you encounter a bug, error, or unexpected behavior. Collects context and creates a GitHub issue.
---

# Submit a Plain Bug Report

## 1. Get bug details from the user

Ask the user for:

- **Title** (required) — a short summary of the bug
- **Description** (required) — what happened and how to trigger it.

Keep it concise but include whichever of these are available:

- **Reproduction steps** — a minimal code snippet or command sequence that triggers the bug. Most valuable when the bug is reproducible.
- **Actual error** — the traceback or unexpected output verbatim (trimmed to the relevant parts).
- **Root cause / fix** — if you have high-confidence insight, include it. Helps maintainers triage faster.

Not every bug will have all three — a feature that's missing or behaves incorrectly may just need a clear description.

## 2. Collect environment info

Run these commands to auto-detect environment details:

```bash
uv run plain --version
```

```bash
uv run python --version
```

```bash
uname -s -r
```

## 3. Confirm with user

Show the user the full issue title and body before submitting. Do NOT submit without explicit approval.

## 4. Submit via `gh`

Create the issue using the GitHub CLI:

```bash
gh issue create --repo dropseed/plain --title "<title>" --body "<body>"
```

The body should follow this format:

```
<user's bug description>

## Environment

- Plain: <version>
- Python: <version>
- OS: <uname output>

---

*Submitted via the `/plain-bug` skill.*
```

## 5. Report the result

Show the issue URL returned by `gh` so the user can follow up.

## Guidelines

- **No private info** — Don't include file paths, env vars, API keys, secrets, database URLs, or other project-specific details. Only include Plain/Python versions, OS, and the bug description.
- **Confirm before submitting** — Always show the full issue body to the user and get approval before creating.
- **No label needed** — Maintainers will triage and label the issue.
