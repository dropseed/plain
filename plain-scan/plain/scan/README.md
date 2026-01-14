# plain.scan

**Scan websites for HTTP security misconfigurations.**

- [Overview](#overview)
- [Command line usage](#command-line-usage)
    - [Output formats](#output-formats)
    - [Disabling audits](#disabling-audits)
    - [Verbose mode](#verbose-mode)
- [Using the Scanner programmatically](#using-the-scanner-programmatically)
- [Audits](#audits)
    - [Required audits](#required-audits)
    - [Optional audits](#optional-audits)
    - [Conditional audits](#conditional-audits)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain Scan checks production websites for common HTTP security issues: headers, SSL certificates, redirects, and server-level security settings.

You can try it immediately without installing anything:

```bash
uvx plain-scan github.com
```

Or visit [plainframework.com/scan](https://plainframework.com/scan/) to scan URLs in your browser.

Plain Scan focuses on practical checks you should actually pay attention to. Every failure is highly actionable with specific guidance on what to fix.

## Command line usage

Scan any URL by passing a domain or full URL:

```bash
plain-scan example.com
plain-scan https://example.com/login
```

Bare domains default to HTTPS.

### Output formats

Choose between CLI, JSON, or Markdown output:

```bash
plain-scan example.com --format cli      # default, human-readable
plain-scan example.com --format json     # machine-readable
plain-scan example.com --format markdown # for reports
```

### Disabling audits

Skip specific audits using `--disable`:

```bash
plain-scan staging.example.com --disable hsts --disable csp
```

This is useful for staging servers where you might not have HSTS configured yet.

Available audits to disable: `csp`, `hsts`, `tls`, `redirects`, `content-type-options`, `frame-options`, `referrer-policy`, `cookies`, `cors`.

### Verbose mode

See the full response chain including headers and cookies:

```bash
plain-scan example.com --verbose
```

## Using the Scanner programmatically

You can use the [`Scanner`](./scanner.py#Scanner) class directly in Python:

```python
from plain.scan.scanner import Scanner

scanner = Scanner("https://example.com")
result = scanner.scan()

print(f"URL: {result.url}")
print(f"Passed: {result.passed}")
print(f"Audits: {result.passed_count}/{result.total_count} passed")

for audit in result.audits:
    status = "PASS" if audit.passed else "FAIL"
    print(f"  [{status}] {audit.name}")
    for check in audit.checks:
        print(f"    - {check.name}: {check.message}")
```

Disable specific audits by passing a set of slugs:

```python
scanner = Scanner("https://staging.example.com", disabled_audits={"hsts", "csp"})
```

The scan result can be serialized to JSON:

```python
import json
result_dict = result.to_dict()
print(json.dumps(result_dict, indent=2))
```

See [`ScanResult`](./results.py#ScanResult), [`AuditResult`](./results.py#AuditResult), and [`CheckResult`](./results.py#CheckResult) for the full result structure.

## Audits

Security checks are organized into audits. Each audit first checks if a security feature is detected, then runs specific checks to verify proper configuration.

### Required audits

These audits fail if the security feature is missing or misconfigured:

| Audit                    | Description                                                     |
| ------------------------ | --------------------------------------------------------------- |
| **CSP**                  | Content Security Policy protects against XSS and data injection |
| **HSTS**                 | HTTP Strict Transport Security enforces HTTPS connections       |
| **TLS**                  | Validates SSL certificate and connection security               |
| **Redirects**            | Ensures proper HTTP to HTTPS redirects                          |
| **Content-Type-Options** | Prevents MIME-sniffing attacks                                  |
| **Frame-Options**        | Prevents clickjacking attacks                                   |
| **Referrer-Policy**      | Controls referrer information sharing                           |

### Optional audits

These audits only fail if the feature is detected but misconfigured:

| Audit    | Description                                                       |
| -------- | ----------------------------------------------------------------- |
| **CORS** | Cross-Origin Resource Sharing (only needed for cross-origin APIs) |

### Conditional audits

These audits are automatically detected and only checked when relevant:

| Audit       | Description                                            |
| ----------- | ------------------------------------------------------ |
| **Cookies** | Only checked if your site sets cookies in the response |

## FAQs

#### How does the scanner work?

Plain Scan makes a single unauthenticated GET request to the provided URL. It checks what can be inferred from the HTTP response and performs a TLS socket probe. It does not crawl additional pages, execute JavaScript, render in a browser, or follow authenticated flows.

#### Can I use this against development servers?

Yes. Plain Scan works against any URL, including localhost. Keep in mind that some checks (like TLS) may fail on development servers without valid certificates.

#### Why does the scanner flag Google Analytics or Google Tag Manager in my CSP?

These domains host JSONP endpoints that can be exploited to bypass CSP and execute arbitrary JavaScript. This is based on research from Google's CSP Evaluator team. If you must use these services, consider using [nonce-based or hash-based CSP](https://web.dev/articles/strict-csp) instead of domain allowlisting.

#### What about COOP/COEP/CORP headers?

Cross-origin isolation headers are not currently enforced. Most sites do not ship the full header trio yet, so Plain Scan treats them as optional for now.

#### What security standards does Plain Scan follow?

Plain Scan implements checks based on:

- [Google CSP Evaluator](https://github.com/google/csp-evaluator) for Content Security Policy
- [Mozilla Observatory](https://github.com/mdn/mdn-http-observatory) security header guidelines
- OWASP security best practices
- Modern web security standards (CSP Level 3, etc.)

#### What tools complement Plain Scan?

Plain Scan focuses on HTTP-level security checks. For browser-based audits, performance, and client-side security, consider:

- [Lighthouse](https://developer.chrome.com/docs/lighthouse) for browser-based audits
- [Mozilla Observatory](https://observatory.mozilla.org/) for additional header analysis
- [Qualys SSL Labs](https://www.ssllabs.com/ssltest/) for deep SSL/TLS analysis

## Installation

**Web interface (no installation):**

Visit [plainframework.com/scan](https://plainframework.com/scan/) to scan any URL directly in your browser.

**Command line (no installation):**

```bash
uvx plain-scan github.com
```

This uses `uvx` to run plain-scan without adding it as a project dependency.

**As a project dependency:**

```bash
uv add plain.scan
```

Then run scans:

```bash
plain-scan example.com
```

Or use the Python API:

```python
from plain.scan.scanner import Scanner

result = Scanner("https://example.com").scan()
print(f"Passed: {result.passed}")
```
