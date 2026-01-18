#!/usr/bin/env python3
"""
Simple benchmark script for memray profiling.

Usage:
    DATABASE_URL=postgres://postgres:postgres@localhost:5432/plain_example memray run -o bench.bin scripts/benchmark-request.py
    memray stats bench.bin
    memray flamegraph bench.bin
"""

import os
import sys
from pathlib import Path

# Change to example directory to have a valid Plain app
script_dir = Path(__file__).parent
example_dir = script_dir.parent / "example"

if example_dir.exists():
    os.chdir(example_dir)
else:
    print(f"Error: Could not find example at {example_dir}", file=sys.stderr)
    sys.exit(1)

import plain.runtime  # noqa: E402

plain.runtime.setup()

from collections.abc import Iterable  # noqa: E402
from io import BytesIO  # noqa: E402
from typing import cast  # noqa: E402

from plain.internal.handlers.wsgi import WSGIHandler  # noqa: E402


def create_environ(path="/"):
    """Create WSGI environ for a GET request."""
    return {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "443",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "SCRIPT_NAME": "",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": BytesIO(b""),
        "wsgi.errors": None,
        "wsgi.multiprocess": True,
        "wsgi.multithread": False,
        "wsgi.run_once": False,
    }


def start_response(status, headers):
    """Minimal WSGI start_response."""
    pass


def main():
    handler = WSGIHandler()
    environ = create_environ()

    print("Warmup request...")
    list(cast(Iterable[bytes], handler(environ.copy(), start_response)))

    print("Running 100 requests for profiling...")
    for i in range(100):
        env = environ.copy()
        env["wsgi.input"] = BytesIO(b"")
        list(cast(Iterable[bytes], handler(env, start_response)))

    print("Done!")


if __name__ == "__main__":
    main()
