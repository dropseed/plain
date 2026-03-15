---
labels:
  - plain-passwords
related:
  - models-encrypted-field
---

# plain-passwords: Argon2id Default Hasher

The only built-in hasher is `PBKDF2PasswordHasher` (SHA256, 720k iterations). PBKDF2 is still acceptable but is no longer the recommended choice. OWASP, NIST (SP 800-63B), and most modern frameworks recommend **Argon2id** as the primary password hashing algorithm.

## Why Argon2id over PBKDF2

PBKDF2 is CPU-bound only. An attacker with GPUs or ASICs can parallelize PBKDF2 cracking cheaply. Argon2id is **memory-hard** — it requires a configurable amount of RAM per hash, making GPU/ASIC attacks dramatically more expensive.

- **OWASP 2024**: Argon2id is the primary recommendation (m=19456 KiB, t=2, p=1)
- **NIST SP 800-63B**: Lists Argon2 as an approved algorithm
- **Ruby (Devise)**: bcrypt default, Argon2 via gem
- **Laravel**: bcrypt default, Argon2id via `Hash::driver('argon2id')`
- **Rails 7.1+**: bcrypt default
- **Django**: PBKDF2 default, Argon2 available as first entry in docs recommendation

Django kept PBKDF2 as default to avoid a compiled dependency (`argon2-cffi`). Plain doesn't need to inherit that constraint — Plain already has compiled dependencies and targets a more opinionated audience.

## Current state

The hasher infrastructure is already solid:

- `BasePasswordHasher` abstract class with `encode`, `verify`, `decode`, `must_update`, `harden_runtime`
- `PASSWORD_HASHERS` setting — first entry is the active hasher, remaining entries verify legacy hashes
- `check_password` auto-rehashes on login when `must_update` returns True
- `identify_hasher` routes by algorithm prefix in the stored hash

This means switching the default is seamless for existing users — old PBKDF2 hashes continue to verify, and passwords get transparently upgraded to Argon2id on next login.

## Design

### Ship two hashers

```python
# plain-passwords/plain/passwords/hashers.py

class Argon2idPasswordHasher(BasePasswordHasher):
    """
    Argon2id password hasher (recommended).
    Memory-hard, resistant to GPU/ASIC attacks.
    """
    algorithm = "argon2id"
    time_cost = 2        # iterations
    memory_cost = 19456  # KiB (~19 MiB) — OWASP minimum
    parallelism = 1
    hash_length = 32
    salt_length = 16

class PBKDF2PasswordHasher(BasePasswordHasher):
    # ... unchanged, kept for verifying existing hashes
```

### New default setting

```python
PASSWORD_HASHERS: list = [
    "plain.passwords.hashers.Argon2idPasswordHasher",
    "plain.passwords.hashers.PBKDF2PasswordHasher",
]
```

PBKDF2 stays in the list so existing passwords still verify. On next login, they're transparently re-hashed with Argon2id.

### Dependency

`argon2-cffi` — the standard Python Argon2 binding. Pure C extension, binary wheels available for all platforms. Already used by Django users who follow the docs recommendation.

Alternatively, `argon2-cffi-bindings` is the lower-level package — but `argon2-cffi` provides the nicer `PasswordHasher` API and is the community standard.

## Implementation

1. Add `argon2-cffi` to `plain-passwords` dependencies
2. Add `Argon2idPasswordHasher` to `hashers.py`
3. Change `default_settings.py` to list Argon2id first, PBKDF2 second
4. Add `must_update` to detect when parameters (memory_cost, time_cost) increase
5. Add `harden_runtime` for timing attack mitigation
6. Tests for encode/verify/upgrade cycle

## Parameter tuning

OWASP recommends calibrating parameters so hashing takes ~1 second on your target hardware. The defaults above (m=19456, t=2, p=1) are OWASP's minimum recommendation. A `plain passwords benchmark` management command could help users tune for their server.

## Open questions

- Should we also ship a `BCryptPasswordHasher` for users who prefer bcrypt (e.g., migrating from Rails/Laravel)? It's a well-understood algorithm and `bcrypt` is a common Python package. Could be useful for compatibility but adds another dependency.
- Should the default memory cost be higher than OWASP minimum? 19 MiB is conservative. 64 MiB is common in practice. But higher memory costs can cause issues on constrained containers.
