"""Importing `plain.server` doesn't load the server.

`plain.server.inprocess` handles requests with no arbiter, workers or
reloader, and the test client imports it on every run.
"""

import subprocess
import sys

LIST_LOADED_SERVER_MODULES = """
import sys
import plain.server.inprocess

print([
    name for name in sys.modules
    if name in ("plain.server.app", "plain.server.arbiter")
])
"""


def test_the_in_process_server_does_not_import_the_server_application():
    loaded = subprocess.run(
        [sys.executable, "-c", LIST_LOADED_SERVER_MODULES],
        capture_output=True,
        text=True,
        check=True,
    )

    assert loaded.stdout.strip() == "[]"
