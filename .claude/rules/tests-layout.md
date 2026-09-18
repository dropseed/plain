---
paths:
  - "**/tests/**"
---

# Public vs internal tests

Tests split by what they prove, not who typed them:

- **`<package>/tests/public/`** — the **contract**. Failures mean a user-visible behavior is broken.
- **`<package>/tests/internal/`** — the **change detector**. Failures mean something shifted; you decide whether it should have.

**Where does my test go?** Public tests assert at the layer the user interacts with.

- _Features_ (jobs, auth, requests, sessions): the user-interaction layer is end-to-end. `Client()`, run the worker, observe the user-visible outcome. Tests of the underlying queryset, middleware, or model in isolation sit _below_ that layer → internal.
- _Utility functions_ (`reverse_absolute`, `parse_dotenv`, `generate_code`): the function call _is_ the user-interaction layer. A return-value test is the contract → public.

Still unsure? **Would a failure surprise a user reading the changelog?** If yes → public.

**Internal-test tells:**

- Imports from `_internal`, or asserts on a symbol not in `__all__` / `plain docs <pkg> --api`
- Pokes module-level state or private attributes
- Pins instrumentation surface — OTel spans/metrics, log shape, internal counters
- Stages drift/edge scenarios with heavy helper machinery
- Wouldn't survive a feature rewrite

**Conventions:**

- **Lifecycle**: `internal/` tests are regenerable — delete and rewrite freely when features change. `public/` tests evolve deliberately.
- **Promotion**: when a test crosses into contract territory, move from `internal/` to `public/`; the reverse isn't a thing.

Both directories run in the normal pytest suite and must pass. Shared fixtures in `tests/conftest.py` are inherited by both.
