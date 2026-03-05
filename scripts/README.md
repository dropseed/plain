# Scripts

## Development

| Script                       | Purpose                                                        |
| ---------------------------- | -------------------------------------------------------------- |
| `./scripts/fix`              | Format and lint (ruff, oxlint, prettier)                       |
| `./scripts/test [package]`   | Run test suite for all or one package                          |
| `./scripts/pre-commit`       | Full pre-commit validation (fix, type-check, tests, preflight) |
| `./scripts/makemigrations`   | Create database migrations                                     |
| `./scripts/type-check <dir>` | Type check a directory with ty                                 |
| `./scripts/type-validate`    | Validate type annotations across all packages                  |
| `./scripts/install`          | Install all packages in development mode                       |
| `./scripts/publish`          | Publish packages to PyPI                                       |

## Server Testing

These scripts start the example server on a random port and run protocol-level tests against it. Each can also target an already-running server via `host:port`.

| Script                      | What it tests                                                                                                                                                                                     | Test count |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `./scripts/h1spec`          | HTTP/1.1 conformance (RFC 9112) — request parsing, headers, chunked encoding, keep-alive, connection limits                                                                                       | 32         |
| `./scripts/h2spec`          | HTTP/2 conformance (RFC 7540) via [h2spec](https://github.com/summerwind/h2spec). Starts server with a temporary self-signed TLS cert. Requires `brew install h2spec`.                            | ~146       |
| `./scripts/autobahn-wstest` | WebSocket protocol conformance (RFC 6455) via the Autobahn testsuite Docker image — fragmentation, UTF-8 validation, close codes, control frames, reserved bits, large payloads. Requires Docker. | 301        |
| `./scripts/server-test`     | Server worker behavior — concurrency, keepalive lifecycle, slow clients, thread pool exhaustion                                                                                                   | varies     |
| `./scripts/server-bench`    | HTTP request throughput benchmarking                                                                                                                                                              | -          |

`h1spec` is run automatically as part of `./scripts/test`. The others are run manually.

### autobahn-wstest

Requires Docker. Runs the [Autobahn testsuite](https://github.com/crossbario/autobahn-testsuite) fuzzing client against the example app's `/ws-echo/` WebSocket endpoint.

```bash
./scripts/autobahn-wstest                    # full suite (301 cases)
./scripts/autobahn-wstest --cases="7.*"      # specific test groups
./scripts/autobahn-wstest host:port          # against running server
```

Results are written to `scratch/autobahn-results/` and parsed by `scripts/autobahn-report.py`.

## Utilities

| Script                           | Purpose                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------- |
| `./scripts/start-example-server` | Sourced by other scripts — starts the example server and exports `$PORT` / `$SERVER_PID` |
| `./scripts/start-postgres`       | Starts a Postgres container if needed and exports `$DATABASE_URL`                        |
| `./scripts/bench-memory`         | Memory usage profiling                                                                   |
| `./scripts/vulture`              | Dead code detection                                                                      |
