# plain-api: Hash API Tokens

API tokens are currently stored as plaintext in the database. Since these are tokens we **issue** (not tokens we receive), we don't need the original value back — we only need to verify incoming tokens. This means we can **hash** them (one-way) instead of encrypting them (reversible).

This is a different problem from encrypted fields. Encryption is for secrets you need back. Hashing is for secrets you only need to verify.

## Current state

```python
# plain-api/plain/api/models.py
token: str = types.CharField(max_length=40, default=generate_token)
```

The full token is stored in the database and looked up with `APIKey.query.get(token=token)`. A database dump or SQL injection exposes every API key.

## Industry patterns

**Sentry**: Stores plaintext token + SHA-256 hash side by side. Lookups use the hash. The plaintext is returned once at creation, then a `PlaintextSecretAlreadyRead` exception prevents re-reading. They still have the plaintext column — this is a known limitation they're working on.

**GitHub**: Personal access tokens are hashed. You see the token once at creation. The prefix (`ghp_`, `gho_`) is stored to identify token type, but the secret part is hashed.

**Stripe**: API keys have a prefix (`sk_live_`) visible in the dashboard, but the full key is only shown once.

The common pattern: **show once, hash, never store plaintext**.

## Design

### Token format

```
pk_<base62_random>
```

A short prefix makes tokens greppable in logs, identifiable by type, and distinguishable from other random strings. The prefix is stored separately for display/identification.

### Storage

```python
class APIKey(models.Model):
    # What the user sees in the dashboard
    token_prefix: str = types.CharField(max_length=10)
    token_last_four: str = types.CharField(max_length=4)

    # What we use for lookups
    token_hash: str = types.CharField(max_length=64)

    # ... existing fields (uuid, name, expires_at, etc.)
```

- `token_prefix` + `token_last_four`: for display in the UI (`pk_...a1b2`)
- `token_hash`: SHA-256 of the full token, used for lookups

### Lookup flow

```python
# Incoming request has token "pk_abc123..."
hash = sha256(token).hexdigest()
api_key = APIKey.query.get(token_hash=hash)
```

SHA-256 is fine here (not bcrypt/PBKDF2) because API tokens are high-entropy random strings, not human-chosen passwords. Brute force against 20 random bytes is not feasible.

### Creation flow

```python
key, plaintext_token = APIKey.create_key(name="My API Key")
# plaintext_token is returned ONCE — it is never stored
# key.token_hash contains the SHA-256 hash
```

The plaintext token is returned from the creation method but never persisted. The UI shows it once with a "copy now, you won't see this again" warning.

## Migration

1. Add `token_prefix`, `token_last_four`, `token_hash` fields
2. Data migration: for each existing key, compute the hash from the plaintext token, extract prefix and last four
3. Update authentication to look up by hash
4. Remove `token` plaintext column

Existing tokens continue to work — they're hashed during migration. No user action required.

## Open questions

- Should there be a constant-time comparison for the hash lookup, or is the DB index lookup sufficient? (DB index lookup is a timing oracle, but the token is high-entropy so this doesn't matter in practice.)
- Should `generate_token()` use `secrets.token_urlsafe()` instead of `os.urandom` + hex encoding? URL-safe base64 is denser (more entropy per character).
- What should the prefix convention be? `pk_` (plain key)? Let the user configure it?
