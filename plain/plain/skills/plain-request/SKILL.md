---
name: plain-request
description: Makes HTTP requests to test URLs, check endpoints, fetch pages, or debug routes. Use when asked to look at a URL, hit an endpoint, test a route, or make GET/POST requests.
---

# Making HTTP Requests

Use `uv run plain request` to make test requests against the dev database.

## Basic Usage

```
uv run plain request /path
```

## With Authentication

```
uv run plain request /path --user 1
```

## With Custom Headers

```
uv run plain request /path --header "Accept: application/json"
```

## POST/PUT/PATCH with Data

```
uv run plain request /path --method POST --data '{"key": "value"}'
```

## Limiting Output

```
uv run plain request /path --no-body    # Headers only
uv run plain request /path --no-headers # Body only
```
