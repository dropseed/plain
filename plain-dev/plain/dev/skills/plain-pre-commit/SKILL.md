---
name: plain-pre-commit
description: Runs pre-commit checks before finalizing changes. Use this when you've finished making code changes to verify everything passes before committing.
---

# Pre-commit Checks

Run this when you've finished making changes to catch any issues before committing.

```
uv run plain pre-commit
```

Runs code checks, preflight validation, migration checks, build, and tests.

If checks fail, fix the issues and re-run.
