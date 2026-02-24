# plain-pageviews: Dashboard

- Add a dashboard view to pageviews admin with key metrics and breakdowns
- Inspired by simple analytics dashboards (Fathom, Plausible, etc.)

## Summary Cards

- **Visitors** — unique session_id count for the period
- **Pageviews** — total pageview count for the period
- **Bounce Rate** — percentage of sessions with only one pageview
- **Avg. Duration** — average time between first and last pageview in a session (sessions with one pageview excluded)

## Date Range Filter

- Preset options: Today, 7 Days, 30 Days, 90 Days, 12 Months
- Default to 30 Days

## Traffic Overview Chart

- Line/dot chart showing visitors and pageviews over time
- X-axis: dates in the selected range
- Y-axis: count
- Two series: visitors (unique sessions per day) and pageviews (total per day)
- Use a simple charting approach (SVG or lightweight JS — no heavy chart libraries)

## Top Pages Table

- Columns: Page (URL path), Views, Visitors
- Sorted by views descending
- Truncate long paths with ellipsis
- Limit to top 10 (or configurable)

## Top Referrers Table

- Columns: Source, Visitors
- Group by referrer domain (strip paths)
- "Direct" for null/empty referrer
- Sorted by visitors descending
- Limit to top 10

## Implementation Notes

- All queries use the existing Pageview model — no new models needed
- Session grouping based on `session_id` field
- Visitor = unique `session_id` (not `user_id`, since anonymous visitors matter)
- Dashboard should be the default/landing view in the pageviews admin section
- Consider caching or materializing daily aggregates if query performance becomes an issue at scale
