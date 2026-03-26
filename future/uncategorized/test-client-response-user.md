# Test client: move response.user to response.request.user

`plain/test/client.py` — the test client soft-imports `plain.auth` and attaches the request's authenticated user onto the _response_ object. This leaks request context into the response, creates a hidden dependency on `plain.auth`, and is conceptually wrong (responses don't have users). Cleaner access would be `response.request.user`.
