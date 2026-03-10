---
packages:
  - plain-oauth
related:
  - models-encrypted-field
  - api-hashed-tokens
---

# plain-oauth: Encrypt OAuth Tokens at Rest

OAuth access tokens and refresh tokens in `OAuthConnection` are stored as plaintext `CharField`s. These are third-party credentials we **need back** to make API calls, so they require reversible encryption (not hashing).

## Current state

```python
# plain-oauth/plain/oauth/models.py
access_token: str = types.CharField(max_length=2000)
refresh_token: str = types.CharField(max_length=2000, required=False)
```

A database compromise exposes every user's OAuth tokens for every connected provider. An attacker could impersonate users on GitHub, Slack, Google, etc.

## Industry patterns

**django-allauth**: Changed `STORE_TOKENS` default to `False` in v0.52.0. If you don't need tokens after auth, don't store them. If you do store them, they're plaintext — encryption was requested in 2014 (issue #557) and closed as "not planned."

**Sentry**: Recently migrated `Identity.data` (which holds OAuth tokens) to `EncryptedJSONField` using Fernet encryption.

**GitLab**: Encrypts OAuth/integration tokens using `attr_encrypted`, migrating to Rails-native encryption.

**Google, Square, Twitter**: All recommend encrypting OAuth tokens at rest in their developer documentation.

## Design

### Option A: Use EncryptedCharField (depends on models-encrypted-field proposal)

```python
class OAuthConnection(models.Model):
    access_token: str = types.EncryptedCharField(max_length=2000)
    refresh_token: str = types.EncryptedCharField(max_length=2000, required=False)
```

Simplest approach — swap the field type once `EncryptedCharField` exists. All the encryption mechanics, key rotation, and fallback handling live in the field.

### Option B: Don't store tokens by default (allauth approach)

Add a `OAUTH_STORE_TOKENS` setting (default `False`). Only persist tokens when the application actually needs them for subsequent API calls. Many OAuth integrations only need tokens during the login flow.

This could be combined with Option A — when `OAUTH_STORE_TOKENS = True`, use encrypted fields.

## Recommendation

Option A is the right default. Plain's OAuth package is typically used by products that need ongoing API access (not just login), so tokens need to be stored. The allauth "don't store" approach makes sense for auth-only flows but is too limiting as the default.

Once `models-encrypted-field` lands, this is a one-line field type change plus a data migration.

## Migration

1. Depends on `models-encrypted-field` landing first
2. Change field types from `CharField` to `EncryptedCharField`
3. Data migration to encrypt existing plaintext tokens
4. Consider adding `OAUTH_STORE_TOKENS` setting for users who don't need persistent tokens

## Open questions

- Should `access_token` and `refresh_token` remain separate fields, or should they be combined into a single `EncryptedJSONField` (like Sentry's `Identity.data`)? Separate fields are simpler and match the current API. A JSON blob would allow storing additional token metadata without schema changes.
- Should there be a management command to decrypt/re-encrypt tokens during key rotation, or is the general `plain encrypted-field rotate` command sufficient?
