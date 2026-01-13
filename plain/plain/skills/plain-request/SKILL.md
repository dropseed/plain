---
name: plain-request
description: Makes test HTTP requests against the development database with auth support. Use when debugging endpoints or testing API responses.
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
