# plain-dev: WebSocket Development Companion

- WebSocket server integrated into `plain dev` poncho processes
- Browser script injected via middleware or template tag when `DEBUG=True`
- Use [idiomorph](https://github.com/bigskysoftware/idiomorph) for DOM morphing instead of full page refreshes
- Based on ideas from [repaint](https://github.com/dropseed/repaint) project

## Live Reloading

- Template changes → morph DOM with idiomorph (preserves form state, scroll position)
- Python changes → full refresh after server restart
- CSS changes → hot reload stylesheets without page refresh
- Hook into existing `plain.internal.reloader` file watching
