#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CHECKER = Path(__file__).with_name("check-pypi-artifacts.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifacts-dir", default="artifacts/release")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    arguments = parser.parse_args()
    completed = subprocess.run(
        (
            sys.executable,
            str(CHECKER),
            "--package",
            arguments.package,
            "--version",
            arguments.version,
            "--artifacts-dir",
            arguments.artifacts_dir,
            "--wait",
            "--interval-seconds",
            str(arguments.interval_seconds),
            "--timeout-seconds",
            str(arguments.timeout_seconds),
        ),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
