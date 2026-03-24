# plain: File-Based Secrets Loading

- Extend settings loading to support Docker/Kubernetes file-based secrets pattern
- Check for `PLAIN_<VAR>_FILE` environment variable pointing to file path
- Automatically check `/run/secrets/<lowercase_var>` as fallback (Docker convention)
- Maintain backward compatibility - env vars take precedence over files
- Strip whitespace/newlines from file contents
- Use existing type parsing (`_parse_env_value`) for file contents
- No new dependencies required (Python stdlib only)

## Loading Priority

1. `PLAIN_<VAR>` environment variable (highest - existing behavior)
2. `PLAIN_<VAR>_FILE` environment variable → read file at path
3. `/run/secrets/<lowercase_var>` file if exists (Docker/K8s default)
4. Default value from settings (lowest - existing behavior)

## Benefits

- Docker/Kubernetes native - works with container orchestration secrets
- PaaS compatible - Railway, Render, Fly.io continue using env vars
- Secure - files can have restrictive permissions (0400)
- Industry standard - follows MySQL/Postgres official image patterns
- Foundation for future secrets manager integration (optional)

## Implementation

Modify `plain/plain/runtime/user_settings.py`:

- Add `_read_secret_file(file_path, setting_name)` helper method
- Extend `_load_env_settings()` to check file sources after env vars
- Handle errors gracefully (missing files, permissions, etc.)
- Add tests for file loading and priority order
- Update `plain/plain/runtime/README.md` with examples

## Docker Compose Example

```yaml
services:
  app:
    secrets:
      - secret_key
    environment:
      # Optional: explicit file path
      PLAIN_DATABASE_PASSWORD_FILE: /run/secrets/db_password

secrets:
  secret_key:
    file: ./secrets/secret_key.txt
  db_password:
    file: ./secrets/db_password.txt
```

## Edge Cases

- Missing file → skip silently, try next source
- No read permission → log warning, continue
- Empty file → valid (empty string)
- Symlinks → follow them (Docker secrets are symlinks)
- Type parsing errors → fail with clear message

## Connection to encrypted fields

This proposal is a prerequisite for good encrypted field key management. `SECRET_KEY` is used to derive encryption keys for `EncryptedTextField`/`EncryptedJSONField` (already shipped), so file-based secrets loading ensures self-hosted customers can securely provide `SECRET_KEY` via Docker/K8s secrets rather than environment variables.

Sentry takes a different approach — storing encryption keys as separate files on disk, independent from their Django SECRET_KEY. The file-based secrets approach here is simpler (one mechanism for all secrets) and covers the same use case. A self-hosted customer would mount their `SECRET_KEY` as a Docker secret file, and both signing and encryption derive from it.
