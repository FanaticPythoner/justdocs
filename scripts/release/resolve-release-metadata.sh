#!/usr/bin/env bash
set -euo pipefail

case "${EVENT_NAME:-}" in
  workflow_dispatch)
    tag="${INPUT_TAG:-}"
    ;;
  push)
    if [[ "${REF_TYPE:-}" != "tag" ]]; then
      echo "Release push requires a tag ref." >&2
      exit 1
    fi
    tag="${REF_NAME:-}"
    ;;
  *)
    echo "Unsupported release event '${EVENT_NAME:-}'." >&2
    exit 1
    ;;
esac

if [[ -z "$tag" ]]; then
  echo "A tag is required for manual releases." >&2
  exit 1
fi

read -r package_version prerelease < <(
  python - <<'PY'
from pathlib import Path
import tomllib

from packaging.version import InvalidVersion, Version

raw = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
try:
    version = Version(raw)
except InvalidVersion as error:
    raise SystemExit(f"Invalid pyproject.toml version '{raw}': {error}") from error
print(raw, str(version.is_prerelease).lower())
PY
)

if [[ "$tag" != "v${package_version}" ]]; then
  echo "Tag '$tag' does not match pyproject.toml version '${package_version}'." >&2
  exit 1
fi

git fetch --force --tags origin "refs/tags/${tag}:refs/tags/${tag}"
release_sha="$(git rev-list -n 1 "$tag")"
checkout_sha="$(git rev-parse --verify 'HEAD^{commit}')"
if [[ "$checkout_sha" != "$release_sha" ]]; then
  echo "Checked-out commit '$checkout_sha' does not match tag '$tag' at '$release_sha'." >&2
  exit 1
fi
if [[ "${EVENT_NAME:-}" == 'push' ]]; then
  event_sha="$(git rev-parse --verify "${EVENT_SHA:?EVENT_SHA must be set.}^{commit}")"
  if [[ "$event_sha" != "$release_sha" ]]; then
    echo "Push commit '$event_sha' does not match tag '$tag' at '$release_sha'." >&2
    exit 1
  fi
fi
git fetch --no-tags --force origin main:refs/remotes/origin/main
git merge-base --is-ancestor "$release_sha" refs/remotes/origin/main

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "tag=$tag"
    echo "prerelease=$prerelease"
    echo "release_ref=$release_sha"
    echo "release_sha=$release_sha"
  } >> "$GITHUB_OUTPUT"
else
  printf 'tag=%s\n' "$tag"
  printf 'prerelease=%s\n' "$prerelease"
  printf 'release_ref=%s\n' "$release_sha"
  printf 'release_sha=%s\n' "$release_sha"
fi
