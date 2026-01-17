---
name: annotations
description: Workflow for adding type annotations to Plain packages. Use this when adding or improving type coverage.
---

# Type Annotation Workflow

We are gradually adding type annotations using Python 3.13+.

## Workflow

1. **Check current coverage**:

    ```
    uv run plain code annotations <directory> --details
    ```

2. **Add annotations**: Focus on function/method signatures (parameters and return types)

3. **Type check**:

    ```
    ./scripts/type-check <directory>
    ```

4. **Format**: `./scripts/fix`

5. **Test**: `./scripts/test <package>`

6. **Verify improvement**:

    ```
    uv run plain code annotations <directory>
    ```

7. **Add to validation**: Once a directory reaches 100% coverage, add it to `FULLY_TYPED_PATHS` in `scripts/type-validate`

## Guidelines

- Add `from __future__ import annotations` when necessary
- Focus on public APIs and user-facing methods first
- Don't annotate `__init__` return types (type checkers infer `None`)
- Use explicit `return None` for functions with `-> Type | None` return type
- Some Django-style ORM patterns are inherently difficult to type - that's okay
- Goal is progress, not perfection

## Example

```bash
# Check coverage
uv run plain code annotations plain/plain/assets --details

# After adding annotations...
./scripts/type-check plain/plain/assets
./scripts/fix
./scripts/test plain
uv run plain code annotations plain/plain/assets  # Should show 100%
```
