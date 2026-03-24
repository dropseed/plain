# plain-forms: Return 422 for Invalid Form Submissions

- `FormView.form_invalid()` currently returns 200 OK when re-rendering forms with errors
- Should return 422 Unprocessable Entity instead (semantically correct)
- Aligns with Rails 7 and Laravel conventions
- API views already return 400 for validation errors

## Implementation

- Change `form_invalid()` in `plain/plain/views/forms.py` to return `Response(..., status=422)`
- Configure plain-htmx to swap on 422 by default (HTMX doesn't swap 4xx by default)

## HTMX Consideration

HTMX default `responseHandling`:

```js
{ code: '[45]..', swap: false, error: true }  // No swap on 4xx
```

plain-htmx should add to its JS initialization:

```js
htmx.config.responseHandling.unshift({ code: '422', swap: true, error: false });
```

This makes HTMX behave like Rails Turbo (which swaps on 4xx/5xx for form errors).

## Cloudflare Caveat

Cloudflare can strip response bodies from 422 responses in some configurations. This is a known issue affecting Rails/Turbo users too. Workarounds exist (configure Cloudflare or use DNS-only mode). Not a reason to avoid correct HTTP semantics.

## References

- [Rails PR #41026: Use 422 for form errors](https://github.com/rails/rails/pull/41026)
- [Turbo Handbook](https://turbo.hotwired.dev/handbook/drive)
