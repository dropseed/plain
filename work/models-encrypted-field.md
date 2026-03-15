---
labels:
  - plain-models
related:
  - file-based-secrets
  - oauth-encrypt-tokens
  - api-hashed-tokens
---

# plain-models: Encrypted Field

A model field that transparently encrypts values before writing to Postgres and decrypts on read. For storing third-party credentials, API secrets, and other sensitive data that the application needs back in plaintext.

This is **not** for passwords or tokens you issue — those should be hashed (one-way). This is for secrets you receive from others and need to use later (integration passwords, OAuth tokens, webhook signing keys).

## Industry context

- **Rails 7+**: Built-in `encrypts :field_name` — one-line declaration, deterministic and non-deterministic modes, key rotation
- **Laravel**: Built-in `'field' => 'encrypted'` cast — AES-256-CBC, uses APP_KEY, rotation via APP_PREVIOUS_KEYS
- **Sentry**: Custom `EncryptedJSONField` using Fernet, rolling out field by field (2024-2025)
- **GitLab**: `attr_encrypted` gem, migrating to Rails-native encryption
- **Django**: No built-in support. Fragmented third-party ecosystem (`django-fernet-encrypted-fields`, etc.)

Plain should follow Rails/Laravel in making this a first-class framework feature.

## Design

### Usage

```python
from plain import models
from plain.models import types

class Integration(models.Model):
    name: str = types.CharField(max_length=100)
    api_secret: str = types.EncryptedCharField(max_length=500)
    config: dict = types.EncryptedJSONField()
```

Reads and writes work normally — encryption is invisible to application code.

### Encryption scheme

- **Algorithm**: Fernet (AES-128-CBC + SHA-256 HMAC) via Python `cryptography` library
- **Key derivation**: PBKDF2 from `SECRET_KEY` with a fixed salt unique to encrypted fields (not using SECRET_KEY directly as the Fernet key)
- **Storage**: base64-encoded ciphertext in a `TextField` column (ciphertext is always longer than plaintext)
- **Column type**: Always `text` in Postgres regardless of the logical field type — ciphertext length is unpredictable

### Key rotation

Follow the existing `SECRET_KEY_FALLBACKS` pattern:

1. **Decrypt**: try deriving a key from current `SECRET_KEY`, then try each key in `SECRET_KEY_FALLBACKS`
2. **Encrypt**: always use current `SECRET_KEY`
3. **Rotate**: management command `plain encrypted-field rotate` that reads and re-saves every row with encrypted fields, re-encrypting with the current key

This is the same pattern the Signer already uses for fallback keys.

### What we can learn from Sentry

Sentry's `EncryptedField` has some smart design choices worth considering:

- **Self-describing format**: `enc:fernet:{key_id}:{data}` — each encrypted value identifies its encryption method and key. This makes migration and debugging easier.
- **Multiple encryption backends**: They support `plaintext`, `fernet`, and (future) `keysets`. The `plaintext` mode is useful for gradual rollout — you can add the field type first, then enable encryption later.
- **Per-row key identification**: The key_id in each value means different rows can use different keys during rotation. No need for a flag day.
- **Backward compatibility**: `EncryptedJSONField` gracefully handles unencrypted JSON data, so existing rows don't break when you change the field type.

We should adopt the self-describing format. It makes the "what key encrypted this?" problem trivial and supports future algorithm changes.

### What we should NOT do

- **Deterministic encryption** (Rails has this for queryable encrypted fields): Adds complexity, weaker security, and the use cases where you need to query an encrypted column by value are rare. If you need to look something up, store a separate hash column.
- **Separate key files on disk** (Sentry does this): Too much operational complexity for most Plain users. Deriving from `SECRET_KEY` is simpler and the key management story is already established. The `file-based-secrets` proposal covers loading `SECRET_KEY` itself from disk.
- **Custom key per field**: Over-engineering. One key derived from `SECRET_KEY` with a per-field salt is sufficient.

## Field types

Start with the most useful ones:

- `EncryptedCharField` — for tokens, passwords, API keys
- `EncryptedTextField` — for longer secrets
- `EncryptedJSONField` — for structured secret data (OAuth token bundles, config blobs)

All store as `text` in Postgres. The "Char" vs "Text" distinction is for application-level validation (max_length), not database storage.

## Limitations

Document these clearly:

- **Cannot query by value**: `Model.query.filter(api_secret="x")` won't work. The encrypted value is different every time (non-deterministic).
- **Cannot index**: No unique constraints, no ordering on encrypted fields.
- **Ciphertext is larger**: A 40-char token becomes ~200 chars of ciphertext. Storage columns must be `text`.
- **Key loss = data loss**: If `SECRET_KEY` and all `SECRET_KEY_FALLBACKS` are lost, encrypted data is unrecoverable. This is already true for sessions and signed data.
- **Not protection against app server compromise**: An attacker with code execution has the key. This protects against DB-level compromise (dumps, backups, SQL injection).

## Dependencies

- `cryptography` library (already widely used, well-maintained, has binary wheels)
- This would be a new dependency for `plain-models`

## Migration story

When adding an `EncryptedCharField` to replace a `CharField`:

1. Add the new encrypted field
2. Write a data migration to copy and encrypt existing values
3. Remove the old field

The management command `plain encrypted-field rotate` handles re-encryption on key change.

## SECRET_KEY reuse vs separate ENCRYPTION_KEY

Currently `SECRET_KEY` is used exclusively for **signing** (HMAC) — cookies, sessions, login links, general data signing. Adding encryption would be a new category of use.

**Reuse SECRET_KEY (recommended):**

- Rails derives encryption keys from the same secret base. Laravel uses `APP_KEY` for everything.
- One fewer secret for self-hosted customers to manage, back up, and lose.
- Cryptographically sound — PBKDF2 with a unique salt per purpose means the derived encryption key and signing keys are independent even from the same root.
- Losing SECRET_KEY is already catastrophic (sessions, cookies, signed data all break). Encryption doesn't make the blast radius meaningfully worse.

**Separate ENCRYPTION_KEY:**

- Signing key compromise wouldn't also mean encryption compromise.
- Independent rotation of signing vs encryption.
- Sentry chose this path (key files on disk, separate from Django's SECRET_KEY).

The salt-per-purpose derivation makes reuse safe. The operational simplicity of one key matters more for Plain's self-hosted audience than the marginal security of key separation. If someone later needs a separate key, the `key` parameter on the field could accept a settings reference.

## Open questions

- Should the `cryptography` dependency live in `plain-models` or in a separate `plain-crypto` package? Keeping it in `plain-models` is simpler but adds a compiled dependency to the models package.
- Should unencrypted values be accepted gracefully (like Sentry) for migration purposes, or should the field always expect encrypted data?
- Should there be a preflight check that warns if encrypted fields exist but `SECRET_KEY` looks like a default/insecure value?
