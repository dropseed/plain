# plain-signing: Remove `dumps`/`loads` convenience functions

- The `dumps` and `loads` functions in `plain/plain/signing.py` are thin wrappers around `TimestampSigner`
- They suggest customizability (choosing a signer) that doesn't exist
- The explicit class usage is clearer: `TimestampSigner(salt="...").sign_object(...)`

## Current state

- `plain-loginlink` already uses explicit pattern with its own `ExpiringSigner`
- Only `plain-passwords` currently uses `signing.dumps/loads`

## Implementation

- Remove `dumps` and `loads` functions from `plain/plain/signing.py`
- Update `plain-passwords` to use `TimestampSigner` directly
- Update any documentation referencing these functions

## Benefits

- Cleaner API - no false suggestion of signer customizability
- More explicit usage pattern
- Consistent with how `plain-loginlink` already works

## Breaking changes

- External users of `signing.dumps/loads` will need to migrate to `TimestampSigner`
