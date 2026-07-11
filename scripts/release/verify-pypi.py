#!/usr/bin/env python3
"""Verify that a package version is visible on PyPI."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_SECONDS = 10.0


def read_published_version(url: str, timeout: float) -> str:
    """Return the package version from one bounded PyPI response."""

    with urllib.request.urlopen(url, timeout=timeout) as response:
        encoded = response.read(MAX_RESPONSE_BYTES + 1)
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
    payload = json.loads(encoded.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
        raise ValueError("JSON info object missing")
    version = payload["info"].get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("JSON info.version missing")
    return version


def main() -> int:
    """Run PyPI verification."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args()
    for name in ("interval_seconds", "timeout_seconds"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be a positive finite number")
    deadline = time.monotonic() + args.timeout_seconds
    package = quote(args.package, safe="")
    version = quote(args.version, safe="")
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    last_error = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            published_version = read_published_version(
                url, min(MAX_REQUEST_SECONDS, remaining)
            )
            if published_version == args.version:
                print(f"PyPI version visible: {args.package} {args.version}")
                return 0
            last_error = f"version mismatch: expected {args.version}, received {published_version}"
        except (
            UnicodeDecodeError,
            ValueError,
            TimeoutError,
            urllib.error.URLError,
            OSError,
        ) as error:
            last_error = str(error)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, remaining))
    print(f"PyPI verification failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
