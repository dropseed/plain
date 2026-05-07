# Per-table autovacuum scale factor on `plaincache_cacheditem`. The Postgres
# default of 0.2 is too lax for a cache table whose rows churn far faster than
# they grow — autovacuum waits for 20% dead tuples, by which point bloat is
# already established.
CACHE_AUTOVACUUM_SCALE_FACTOR: float = 0.1

# TOAST autovacuum scale factor for `plaincache_cacheditem`. Cache values are
# often large enough to TOAST, and every `set()` rewrites the value, leaving
# orphaned TOAST chunks. TOAST has its own autovacuum schedule independent of
# the heap, so it gets its own knob.
CACHE_TOAST_AUTOVACUUM_SCALE_FACTOR: float = 0.05
