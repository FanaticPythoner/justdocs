#!/usr/bin/env bash
set -euo pipefail

: "${RELEASE_TAG:?RELEASE_TAG must be set.}"

python3 scripts/release/verify-pypi.py \
  --package justdocs \
  --version "${RELEASE_TAG#v}" \
  --interval-seconds "${PYPI_VERIFY_INTERVAL_SECONDS:-15}" \
  --timeout-seconds "${PYPI_VERIFY_TIMEOUT_SECONDS:-600}"
