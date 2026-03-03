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

from plain.test import Client  # noqa: E402


def main():
    client = Client()

    print("Warmup request...")
    client.get("/")

    print("Running 100 requests for profiling...")
    for i in range(100):
        client.get("/")

    print("Done!")


if __name__ == "__main__":
    main()
