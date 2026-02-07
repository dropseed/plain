"""
Server-side rendering for React components using PyMiniRacer (embedded V8).

How it works:
1. During `plain build`, Vite creates an SSR bundle (a single JS file that
   exports a render function for each page component).
2. At runtime, the SSR engine loads that bundle into an in-process V8 context.
3. Per-request, it calls the render function with the component name and props,
   getting back an HTML string.
4. That HTML is embedded inside the <div id="app"> so the page has content
   immediately, and React hydrates (attaches event handlers) on the client.

This avoids:
- Running a separate Node.js SSR server
- Subprocess spawning per request
- Any Node.js runtime dependency in production

Requirements:
- `mini-racer` pip package (optional dependency of plain-react)
- An SSR bundle built by Vite (`plain build` handles this)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from plain.json import PlainJSONEncoder

logger = logging.getLogger("plain.react.ssr")

_v8_context = None
_ssr_bundle_loaded = False


def _get_ssr_bundle_path() -> str:
    """Get the path to the built SSR bundle."""
    from plain.runtime import APP_PATH

    return os.path.join(APP_PATH.parent, "app", "assets", "react", "ssr.js")


def _get_v8_context():
    """Get or create the V8 context with the SSR bundle loaded."""
    global _v8_context, _ssr_bundle_loaded

    if _v8_context is not None and _ssr_bundle_loaded:
        return _v8_context

    try:
        from mini_racer import MiniRacer
    except ImportError:
        raise ImportError(
            "SSR requires the 'mini-racer' package. Install it with: uv add mini-racer"
        )

    bundle_path = _get_ssr_bundle_path()
    if not os.path.exists(bundle_path):
        raise FileNotFoundError(
            f"SSR bundle not found at {bundle_path}. Run 'plain build' to create it."
        )

    ctx = MiniRacer()

    # Load the SSR bundle
    with open(bundle_path) as f:
        bundle_code = f.read()

    ctx.eval(bundle_code)

    # Verify the render function exists
    ctx.eval(
        """
        if (typeof __plainReactSSR !== 'function') {
            throw new Error(
                'SSR bundle must export a __plainReactSSR function. '
                + 'Check your vite.config.js SSR configuration.'
            );
        }
        """
    )

    _v8_context = ctx
    _ssr_bundle_loaded = True
    logger.info("SSR V8 context initialized with bundle: %s", bundle_path)

    return ctx


def render_to_string(component: str, props: dict[str, Any]) -> str:
    """
    Render a React component to an HTML string using the embedded V8 engine.

    Args:
        component: The component name (e.g., "Users/Index")
        props: The props dict to pass to the component

    Returns:
        The rendered HTML string

    Raises:
        ImportError: If mini-racer is not installed
        FileNotFoundError: If the SSR bundle hasn't been built
        RuntimeError: If rendering fails
    """
    ctx = _get_v8_context()

    props_json = json.dumps(props, cls=PlainJSONEncoder)

    try:
        html = ctx.eval(f"__plainReactSSR({json.dumps(component)}, {props_json})")
        return html
    except Exception as e:
        logger.warning("SSR render failed for %s: %s", component, e)
        # Return empty string on failure — the client will render it
        return ""


def is_ssr_available() -> bool:
    """Check if SSR is available (mini-racer installed and bundle exists)."""
    try:
        import mini_racer  # noqa: F401
    except ImportError:
        return False

    return os.path.exists(_get_ssr_bundle_path())


def reset_context() -> None:
    """Reset the V8 context (useful after rebuilds)."""
    global _v8_context, _ssr_bundle_loaded
    _v8_context = None
    _ssr_bundle_loaded = False
