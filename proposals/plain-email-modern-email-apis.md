# plain-email: Modern Python Email APIs

- Replace legacy `email.mime.*` classes with modern `email.message.EmailMessage` (Python 3.6+)
- Use `email.policy.EmailPolicy` for consistent encoding, line length, and header handling
- Modernize attachment handling with `EmailMessage.add_attachment()` instead of manual MIME construction
- Remove manual `Charset` manipulation - let policy handle it automatically
- Replace `email.header.Header` usage with policy-based approach
- Maintain all existing security features (header injection prevention)
- Keep public API unchanged - all changes are internal implementation

## Benefits

- Cleaner, more Pythonic code
- Better Unicode handling out of the box
- Simpler attachment API
- Future-proof (actively maintained API)
- Potentially 100-200 fewer lines of code

## Risks

- Policy may handle edge cases differently than current implementation
- Must thoroughly test all email features (attachments, alternatives, templates, Unicode)
- Must ensure header injection prevention is preserved
