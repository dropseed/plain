# Performance

Use the `/plain-optimize` skill for the full performance optimization workflow (capture traces, analyze, fix, verify).

Key commands:

- `uv run plain observer request /path` - Capture a trace and return structured JSON analysis (query counts, duplicates, issues, span tree)
- `uv run plain observer request /path --user 1` - Trace as a specific user (accepts ID or email)
- `uv run plain observer trace <trace-id> --json` - Get raw trace data for a previously captured trace
