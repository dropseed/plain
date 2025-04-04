# CSRF

**Cross-Site Request Forgery (CSRF) protection.**

Plain protects against [CSRF attacks](https://en.wikipedia.org/wiki/Cross-site_request_forgery) through a [middleware](middleware.py) that compares the generated `csrftoken` cookie with the CSRF token from the request (either `_csrftoken` in form data or the `CSRF-Token` header).

## Usage

The `CsrfViewMiddleware` is [automatically installed](../internal/handlers/base.py#BUILTIN_BEFORE_MIDDLEWARE), so you don't need to add it to your `settings.MIDDLEWARE`.

When you use HTML forms, you should include the CSRF token in the form data via a hidden input:

```html
<form method="post">
    {{ csrf_input }}
    <!-- other form fields here -->
</form>
```
