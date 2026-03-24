---
related:
  - diagnose-command
---

# Admin dashboard

Dashboard showing `diagnose` results plus historical trends. pgHero's approach of capturing stats on a schedule and charting them is the right model — you want to see "is cache hit ratio trending down?" not just "what is it right now?"

## Open questions

- Capture stats on a schedule (like pgHero) or compute on-demand? Scheduled capture needs a background job; on-demand is simpler but no historical trends.
