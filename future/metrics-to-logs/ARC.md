# Metrics to logs

Framework-level metrics (query latency, request duration) exported as structured log lines through the existing log pipeline. No new infrastructure — metrics ride stdout to the log drain to ClickHouse.

Each framework package instruments itself with OTel histograms. Without a configured MeterProvider, these are no-ops. plain-observer configures a MeterProvider with a custom exporter that flushes aggregated histograms as structured log lines every 60 seconds — one line per metric per process per interval.

## Sequence

- [ ] [metrics-log-exporter](metrics-log-exporter.md)
- [ ] [metrics-db-query-duration](metrics-db-query-duration.md)
- [ ] [metrics-request-duration](metrics-request-duration.md)
