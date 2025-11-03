# plain-scan changelog

## [0.3.1](https://github.com/dropseed/plain/releases/plain-scan@0.3.1) (2025-11-03)

### What's changed

- Simplified CLI command description for consistency with other Plain commands ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80))

### Upgrade instructions

- No changes required

## [0.3.0](https://github.com/dropseed/plain/releases/plain-scan@0.3.0) (2025-10-31)

### What's changed

- Added `from_dict()` class methods to `ScanResult`, `AuditResult`, `CheckResult`, `ScanMetadata`, `ResponseMetadata`, and `CookieMetadata` to enable reconstruction from JSON/dictionary data ([95372ec](https://github.com/dropseed/plain/commit/95372ec))
- Removed nested checks feature to simplify the check result structure ([95372ec](https://github.com/dropseed/plain/commit/95372ec))
- Removed CSP Trusted Types check as it was informational only and not a practical security requirement ([9cc7ac1](https://github.com/dropseed/plain/commit/9cc7ac1))

### Upgrade instructions

- No changes required

## [0.2.0](https://github.com/dropseed/plain/releases/plain-scan@0.2.0) (2025-10-31)

### What's changed

- Added HTTP status code audit to detect server errors (5xx) and client errors (4xx) ([fc6b822](https://github.com/dropseed/plain/commit/fc6b822))
- Scan metadata now includes complete response information with all HTTP headers and cookies ([7c1fb12](https://github.com/dropseed/plain/commit/7c1fb12), [fc6b822](https://github.com/dropseed/plain/commit/fc6b822))
- Improved CSP `Reporting-Endpoints` validation to verify endpoint names are properly defined ([c89eb33](https://github.com/dropseed/plain/commit/c89eb33))
- Removed overly strict CSP `strict-dynamic` suggestion for allowlist-based policies ([14edaf4](https://github.com/dropseed/plain/commit/14edaf4))
- Removed www canonicalization check as it's not a security requirement ([732b4c0](https://github.com/dropseed/plain/commit/732b4c0))

### Upgrade instructions

- No changes required

## [0.1.1](https://github.com/dropseed/plain/releases/plain-scan@0.1.1) (2025-10-31)

### What's changed

- Plain Scan now sends a custom user-agent header (`plain-scan/<version>`) with a link to the documentation ([1f9978d](https://github.com/dropseed/plain/commit/1f9978d))

### Upgrade instructions

- No changes required

## [0.1.0](https://github.com/dropseed/plain/releases/plain-scan@0.1.0) (2025-10-30)

### What's changed

- Initial release of Plain Scan - a practical security scanner for production websites that checks for HTTP-level security misconfigurations.

### Upgrade instructions

- No changes required
