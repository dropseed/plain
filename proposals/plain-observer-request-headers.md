# plain-observer: Request Header Capture

- Add a setting `OBSERVER_HEADERS` for explicitly listing headers to capture
- Default to htmx-specific headers: `["hx-request", "hx-target", "hx-trigger", "hx-current-url"]`
- Capture headers in middleware and attach to observation records
- Smart storage: skip headers that are missing or empty strings (don't store `hx-request = ""`)
- Design generically so any request header can be captured, not just htmx
- Consider storing as JSON field or separate related table depending on flexibility needs
- Distinguish full page loads from htmx partial updates in analytics
- Debug htmx-specific interaction patterns
- Understand which elements users are interacting with (`hx-target`)
- Track what triggers requests (`hx-trigger`)
- Extensible for future non-htmx headers (e.g., `referer`, `user-agent`, custom correlation IDs)
