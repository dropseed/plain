# Testing

```
uv run plain test [pytest options]
```

- `uv run plain test` - Run all tests
- `uv run plain test -k test_name` - Filter by test name
- `uv run plain test --pdb` - Drop into debugger on failure
- `uv run plain test -x` - Stop on first failure
- `uv run plain test -v` - Verbose output

Use pytest fixtures and conventions. Place tests in `tests/` directory. Use `plain.test.Client` for HTTP request testing.
