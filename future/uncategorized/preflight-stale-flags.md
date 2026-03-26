# Preflight: alert stale flags

Flags track `used_at` (updated every evaluation) and there's an existing `flags.unused_flags` preflight check. A complementary `flags.stale_flags` check could alert on flags that are in code but haven't been evaluated recently (old `used_at`), indicating dead code paths. Would need a configurable staleness threshold.
