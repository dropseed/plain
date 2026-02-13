---
name: plain-bug
description: Submit a bug report for the Plain framework. Use when you encounter a bug, error, or unexpected behavior. Collects context and posts to plainframework.com.
---

# Submit a Plain Bug Report

## 1. Get bug details from the user

Ask the user for:

- **Title** (required) — a short summary of the bug
- **Body** (required) — what happened, steps to reproduce, error output, etc.

## 2. Collect environment info

Run these commands to auto-detect environment details:

```bash
uv run plain --version
```

```bash
python --version
```

```bash
uname -s -r
```

## 3. Submit the bug report

POST the bug report to the Plain API using curl:

```bash
curl -s -X POST https://plainframework.com/api/issues/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "<title>",
    "body": "<body>",
    "plain_version": "<from step 2>",
    "python_version": "<from step 2>",
    "os_info": "<from step 2>"
  }'
```

## 4. Report the result

- If successful (response contains `"status": "created"`), tell the user their bug report was submitted and show the issue ID.
- If there was an error, show the error details and suggest they try again or file the issue manually on GitHub.

## Guidelines

- Always confirm the title and body with the user before submitting.
- Do NOT submit without the user's explicit approval.
- Escape special characters properly in the JSON payload.
