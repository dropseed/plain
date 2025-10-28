# plain-email: Filebased Backend HTML/Text Viewing

- Enhance filebased backend to save `.txt` and `.html` files alongside `.log` files
- Makes email content easily viewable without parsing raw RFC 822 format
- Double-click `.html` to preview email in browser during development
- Cat `.txt` or open in editor for quick reading of plain text content
- Keep `.log` file for debugging (full headers, MIME structure, attachments)

## Current State

- Filebased backend saves emails as `.log` files with raw RFC 822/MIME format
- Includes full headers, multipart boundaries, base64 encoding, etc.
- Not human-readable or easily viewable in browser
- Inherited from Django with unclear use case
- Console backend is more useful for dev (immediate stdout output)

## Proposed Enhancement

Save three files per email with shared timestamp prefix:

```
EMAIL_FILE_PATH/
  20250127-143045-123456.log   # Raw RFC 822 format (existing)
  20250127-143045-123456.txt   # Plain text body only
  20250127-143045-123456.html  # HTML body only (if present)
```

- Parse email message to extract text and HTML parts
- Save each part to separate file for easy access
- Handle multipart emails correctly (extract from appropriate MIME part)
- Skip `.html` if email has no HTML part (text-only emails)
- Backward compatible: still saves `.log` file

## Why It Matters

- **Development workflow**: See how emails actually render in browser
- **Template debugging**: Verify HTML output without SMTP setup
- **Quick testing**: No need to parse MIME format manually
- **No complexity**: Still file-based, no database or server required
- **Email client preview**: See exactly what recipients will see

## Implementation

Modify `plain-email/plain/email/backends/filebased.py`:

- Extract text body: `message.body` attribute
- Extract HTML body: Look for `text/html` alternative in `EmailMultiAlternatives`
- Use same timestamp prefix for all three files
- Write files atomically to avoid partial writes
- Handle encoding correctly (UTF-8 for text/html files)

## Future Enhancements

- Toolbar integration: Browse emails with metadata (subject, from, to, date)
- Use `.eml` extension instead of `.log` (standard email file format)
- Add `.json` metadata file for programmatic access
- Setting to skip `.log` file if not needed (save space)
- Index file (`emails.html`) linking to all captured emails
