# plain-observer: Geolocation for Pageviews

- Add geographic location tracking to pageview observations
- Store country, region/state, and city level data (no precise coordinates)
- Perform geolocation lookup on anonymized IP address
- Anonymize IPs using same approach as Google Analytics (mask last octet for IPv4, last 80 bits for IPv6)
- Never store full IP addresses, only the anonymized version
- Lookup works on masked IPs because geolocation databases use network/subnet blocks, not individual IPs
- Support CDN headers when available (e.g., `CF-IPCountry`, `CloudFront-Viewer-Country`, `X-Vercel-IP-Country`)
- Fallback to IP-based lookup if CDN headers not present
- Add optional setting `OBSERVER_GEOLOCATION_ENABLED` (default `False` for privacy-first approach)
- Consider using MaxMind GeoLite2 database (free, self-hosted) or similar service
- Store as separate fields on observation model: `country_code`, `region`, `city`
- Useful for understanding geographic distribution of users
- Help identify regional performance issues or opportunities
- Privacy-conscious: no personal data, follows GDPR/CCPA best practices
- Self-hosted lookup avoids sending data to third parties

## Implementation Options

- **IP Anonymization**: Use `ipaddress` standard library to mask IPs before lookup
- **Database Choice**: MaxMind GeoLite2 (requires periodic updates) vs. cloud service
- **CDN Headers**: Check for common headers first (fastest), fallback to IP lookup
- **Caching**: Cache lookup results by anonymized IP to reduce database queries
- **Optional Fields**: Make all geo fields nullable since lookups may fail or be disabled

## Privacy Considerations

- Document in README that IPs are anonymized before lookup and storage
- Never log or store full IP addresses
- Allow users to opt-in rather than default-on
- Consider adding `OBSERVER_GEOLOCATION_PRECISION` setting (country-only vs. city-level)
