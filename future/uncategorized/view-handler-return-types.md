---
related:
  - ty-upgrade
---

# View handler return type stubs

The `View` base class has `TYPE_CHECKING`-only stubs for HTTP method handlers (`get`, `post`, etc.) that currently use `-> Any` return types. We want to tighten these to the actual `ViewReturn` union type so type checkers validate return values.

The blocker is that `async def get(self)` overriding `def get(self)` is a legitimate LSP violation in Python's type system — all three major type checkers (mypy, pyright, ty) flag it. An async function's effective return type is `Coroutine[Any, Any, T]`, not `T`, so the override is genuinely incompatible from the type system's perspective.

There is no PEP or typing-sig consensus to carve out a special exception for this. The relevant open proposal is [python/typing #241](https://github.com/python/typing/issues/241) ("Allow subclassing without supertyping") but it has no concrete PEP.

## Options to explore

- **Union return type**: `-> ViewReturn | Coroutine[Any, Any, ViewReturn]` — passes all checkers but ugly
- **Wait for typing improvements** — #241 or similar
- **Separate sync/async base classes** — `View` for sync, `AsyncView` for async, each with properly typed stubs

## Current state

`ViewReturn` is defined and exported from `plain.views.base`. The `TYPE_CHECKING` stubs use `-> Any`. This catches parameter signature mistakes (the primary goal) but doesn't validate return types.
