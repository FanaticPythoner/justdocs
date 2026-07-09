#!/usr/bin/env bash
set -euo pipefail

python_bin="${PYTHON_BIN:-python}"

rm -rf dist build artifacts/release
"$python_bin" -m pip install --upgrade pip build twine
"$python_bin" -m build
"$python_bin" -m twine check dist/*
mkdir -p artifacts/release
cp dist/* install.sh install.ps1 artifacts/release/
manifest="$(mktemp)"
trap 'rm -f "$manifest"' EXIT
(
  cd artifacts/release
  for file in *; do
    sha256sum "$file"
  done
) > "$manifest"
mv "$manifest" artifacts/release/SHA256SUMS.txt
trap - EXIT
