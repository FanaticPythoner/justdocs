#!/usr/bin/env bash
set -euo pipefail

python_bin="${PYTHON_BIN:-python}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct)}"

rm -rf dist build artifacts/release
"$python_bin" -m pip install --upgrade '.[release]'
"$python_bin" -m build
for archive in dist/*.tar.gz; do
  "$python_bin" - "$archive" <<'PY'
import gzip
import os
import sys
import tarfile
import tempfile
from pathlib import Path

archive = Path(sys.argv[1])
epoch = int(os.environ["SOURCE_DATE_EPOCH"])
with tarfile.open(archive, "r:gz") as source, tempfile.NamedTemporaryFile(
    dir=archive.parent,
    delete=False,
) as target:
    temporary = Path(target.name)
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as output,
    ):
        for member in sorted(source.getmembers(), key=lambda item: item.name):
            member.mtime = epoch
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.pax_headers = {}
            if not member.isfile():
                output.addfile(member)
                continue
            payload = source.extractfile(member)
            if payload is None:
                raise SystemExit(f"archive member payload missing: {member.name}")
            with payload:
                output.addfile(member, payload)
os.replace(temporary, archive)
PY
done
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
