---
name: plain-test
description: Runs pytest tests with Plain configured. Use for running tests, debugging failures, or verifying changes.
---

# Running Tests

```
uv run plain test [pytest options]
```

## Examples

- `uv run plain test` - Run all tests
- `uv run plain test -k test_name` - Filter by test name
- `uv run plain test --pdb` - Drop into debugger on failure
- `uv run plain test -x` - Stop on first failure
- `uv run plain test -v` - Verbose output

## Writing Tests

- Use pytest fixtures and conventions
- Place tests in `tests/` directory
- Use `plain.test.Client` for HTTP request testing

## Getting Package Docs

Run `uv run plain docs <package> --source` for detailed API documentation.
