# Performance

Use the `/plain-optimize` skill for the full performance optimization workflow (capture traces, analyze, fix, verify).

Key commands:

- `uv run plain request /path --header "Observer: persist"` - Capture a trace
- `uv run plain observer traces --request-id <id>` - Find traces
- `uv run plain observer trace <trace-id> --json` - Analyze a trace
