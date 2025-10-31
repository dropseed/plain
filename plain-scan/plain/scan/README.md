# plain.scan

**Remotely test for production best practices.**

- [Overview](#overview)
- [Audits](#audits)
- [FAQs](#faqs)
- [Additional Resources](#additional-resources)
- [Installation](#installation)

## Overview

Plain Scan checks your production (or development) websites for common HTTP security misconfigurations—headers, SSL certificates, redirects, and other server-level security settings.

Unlike generic security scanners that flag everything as a potential issue, Plain Scan focuses on **practical checks you should actually pay attention to**. Every failure is **highly actionable** with specific guidance on what to fix.

**Try it now:** Visit [plainframework.com/scan](https://plainframework.com/scan/) or run `uvx plain-scan github.com`

## Audits

Security checks are organized into **actionable audits**. Each audit first checks if the security feature is detected on your site, then runs **specific, practical checks** to verify proper configuration. Results tell you exactly what's wrong and what to fix—no vague warnings or overwhelming noise.

**Smart Defaults: Required vs Optional Audits**

Plain Scan uses **intelligent audit organization** to ensure results are practical and actionable:

**Required audits** (will fail if missing or misconfigured):

- **CSP (Content Security Policy)** - Protects against XSS attacks via content injection
- **HSTS (HTTP Strict Transport Security)** - Enforces HTTPS connections
- **Content Type Options** - Prevents MIME-sniffing attacks
- **Frame Options** - Prevents clickjacking attacks
- **Referrer-Policy** - Controls referrer information sharing
- **Redirects** - Ensures proper HTTP to HTTPS redirects
- **TLS** - Validates SSL certificate and connection security

**Optional audits** (won't fail if not present, only if misconfigured):

- **CORS (Cross-Origin Resource Sharing)** - Only needed for cross-origin API endpoints

**Conditional audits** (automatically detected and only checked when relevant):

- **Cookies** - Only checked if your site sets cookies in the response

This approach ensures you **only see failures for things you should actually fix**, not false positives for features you don't use. For deployment-specific exceptions (e.g., HSTS on staging), use `--disable <audit>` to skip specific checks.

## FAQs

#### Can I use this against development servers?

Yes! Plain Scan can be used against development servers, but it's primarily designed to verify production configurations.

#### Why does the scan fail if a security header is missing?

Required headers (like CSP and HSTS) fail if missing because every production site needs them. See [Audits](#audits) for the complete list of required, optional, and conditional checks. Use `--disable <audit>` for deployment-specific exceptions.

#### Why does the scanner flag Google Analytics or Google Tag Manager in my CSP?

These domains (and similar CDNs) host JSONP endpoints that can be exploited to bypass CSP and execute arbitrary JavaScript, even though they appear "safe". This is based on research from Google's CSP Evaluator team. If you must use these services, consider using [nonce-based or hash-based CSP](https://web.dev/articles/strict-csp) instead of domain allowlisting.

#### Does Plain Scan enforce COOP/COEP/CORP (cross-origin isolation)?

Not yet. Most sites still do not ship the full cross-origin isolation header trio, so we treat it as optional for now. When a site opts into isolation (by sending any of those headers) the plan is to enforce them as a bundle, but we avoid failing scans for teams that do not need SharedArrayBuffer-level capabilities today. This keeps results focused on the widely adopted 80/20 baseline while leaving room to harden checks once adoption increases.

#### What are the scope and limitations of Plain Scan?

Plain Scan makes a single unauthenticated GET request to the provided URL. It checks what can be inferred from the HTTP response and performs a TLS socket probe. It does not:

- Crawl additional pages or resources
- Execute JavaScript or render in a browser
- Follow authenticated flows

Emerging protections like cross-origin isolation headers (COOP/COEP/CORP) are currently informational and only enforced when you explicitly opt in.

## Additional Resources

**Security standards:**

Plain Scan implements checks based on:

- [Google CSP Evaluator](https://github.com/google/csp-evaluator) for Content Security Policy
- [Strict CSP (web.dev)](https://web.dev/articles/strict-csp) - Nonce and hash-based CSP implementation guide
- [Mozilla Observatory](https://github.com/mdn/mdn-http-observatory) security header guidelines
- OWASP security best practices
- Modern web security standards (CSP Level 3, etc.)

**Complementary tools:**

Plain Scan focuses on HTTP-level security checks and intentionally avoids browser rendering and JavaScript analysis. For a complete security picture, consider also using:

- [Lighthouse](https://developer.chrome.com/docs/lighthouse) - Browser-based audits including performance, accessibility, and client-side security
- [Mozilla Observatory](https://observatory.mozilla.org/) - Additional HTTP security header analysis
- [Qualys SSL Labs](https://www.ssllabs.com/ssltest/) - Deep SSL/TLS configuration analysis

## Installation

**Web interface (no installation):**

Visit [plainframework.com/scan](https://plainframework.com/scan/) to scan any URL directly in your browser.

**Command line (no installation):**

```bash
uvx plain-scan github.com
```

This uses `uvx` to run plain-scan without adding it as a project dependency. You can use bare domains (which default to HTTPS) or full URLs.

**As a project dependency:**

```bash
pip install plain.scan
```

Or add to your `pyproject.toml`:

```toml
[project]
dependencies = [
    "plain.scan",
]
```

Then run scans:

```bash
plain-scan github.com
```
