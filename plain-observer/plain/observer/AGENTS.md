# Plain Observer AGENTS.md

- Send a request and record traces: `plain agent request /some/path --user 1 --header "Observer: persist"`
- Find traces by request ID: `plain observer traces --request-id abc-123-def`
- Output raw trace data: `plain observer trace [TRACE_ID] --json`
