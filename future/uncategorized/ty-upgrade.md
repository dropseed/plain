# Upgrade ty to 0.0.26+

ty 0.0.26 introduces ~222 new diagnostics. Many are likely legitimate issues surfaced by stricter checking. Needs a dedicated pass to triage and fix.

Run `uv run ty check 2>&1 | grep "^error" | sort | uniq -c | sort -rn` to see the breakdown. Top categories:

- `invalid-argument-type` (20) — wrong types passed to methods
- `call-non-callable` (9) — calling objects typed as `object`
- `invalid-return-type` (8) — return type mismatches
- `invalid-assignment` (7) — subscript assignments on wrong types
- `invalid-method-override` (9) — LSP violations in form/field subclasses
