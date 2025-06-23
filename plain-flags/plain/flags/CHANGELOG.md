# plain-flags changelog

## [0.18.0](https://github.com/dropseed/plain/releases/plain-flags@0.18.0) (2025-06-23)

### What's changed

- Dropped multi-database support: `Flag.check()` now follows updated standard system-check signature that receives a single `database` keyword argument instead of `databases`. Internally the check no longer loops over multiple connections (d346d81).
- Updated the admin “Unused flags” card to use the new `database` keyword (d346d81).

### Upgrade instructions

- No changes required.
