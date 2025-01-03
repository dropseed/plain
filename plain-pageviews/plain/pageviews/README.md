# plain-pageviews

Track pageviews from the client-side.

## FAQs

### Why not use server-side middleware?

Originally this was the idea. It turns out that tracking from the backend, while powerful, also means you have to identify all kinds of requests *not* to track (assets, files, API calls, etc.). In the end, a simple client-side tracking script naturally accomplishes what we're looking for in a more straightforward way.
