#!/usr/bin/env python3
"""Verify that a package version is visible on PyPI."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    """Run PyPI verification."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout_seconds
    url = f"https://pypi.org/pypi/{args.package}/{args.version}/json"
    last_error = ""
    while time.monotonic() <= deadline:
        try:
            with urllib.request.urlopen(url, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            info = payload.get("info", {})
            if info.get("version") == args.version:
                print(f"PyPI version visible: {args.package} {args.version}")
                return 0
            last_error = "version mismatch"
        except (json.JSONDecodeError, KeyError, TimeoutError, urllib.error.URLError, OSError) as error:
            last_error = str(error)
        time.sleep(args.interval_seconds)
    print(f"PyPI verification failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
