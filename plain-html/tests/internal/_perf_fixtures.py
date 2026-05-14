"""Fixtures shared by the perf regression test and the bench harness.

The bench harness (`plain-html/bench/render.py`) holds the same shapes
plus their Jinja equivalents and a `_find_repo_root()` call that only
works from the repo checkout. We can't import it from a test cleanly,
so the test-relevant subset lives here. Keep this file's cases
synchronized with the inline `CASES` table in `bench/render.py` when
either changes — they're meant to be the same workload.
"""

from __future__ import annotations

# Each case: (label, plain_source, context).
# Sources mirror the inline cases in `bench/render.py` exactly.
PERF_CASES: list[tuple[str, str, dict]] = [
    (
        "tiny",
        "<p>Hello, {name}!</p>",
        {"name": "Dave"},
    ),
    (
        "medium_list",
        """<ul>
            <li :for={item in items}>
                <a href="/i/{item['id']}">{item['name']}</a>
                <span class="meta">{item['count']} views</span>
            </li>
        </ul>""",
        {"items": [{"id": i, "name": f"Item {i}", "count": i * 7} for i in range(50)]},
    ),
    (
        "expression_heavy",
        "<div>" + "".join(f"<span>{{f_{i}}}</span>" for i in range(50)) + "</div>",
        {f"f_{i}": f"value_{i}" for i in range(50)},
    ),
    (
        "nested_loops",
        """<table>
            <tr :for={row in rows}>
                <td :for={cell in row}>{cell}</td>
            </tr>
        </table>""",
        {"rows": [[f"r{r}c{c}" for c in range(8)] for r in range(20)]},
    ),
    (
        "conditionals",
        """<div>
            <p :for={u in users}>
                <strong :if={u['active']}>{u['name']}</strong>
                <span :if={not u['active']}>(inactive: {u['name']})</span>
            </p>
        </div>""",
        {"users": [{"name": f"User {i}", "active": i % 2 == 0} for i in range(50)]},
    ),
]
