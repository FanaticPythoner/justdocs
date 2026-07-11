#!/usr/bin/env bash
set -euo pipefail

release_pep440_tags_array()
{
  local output_name="$1"
  local -n output_ref="$output_name"

  mapfile -t output_ref < <(
    python - <<'PY'
import subprocess

from packaging.version import InvalidVersion, Version

tags = subprocess.run(
    ("git", "tag", "--list", "v*"),
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
versions = []
for tag in tags:
    try:
        versions.append((Version(tag.removeprefix("v")), tag))
    except InvalidVersion:
        continue
for _, tag in sorted(versions, reverse=True):
    print(tag)
PY
  )
}

latest_release_tag()
{
  local tags=()
  release_pep440_tags_array tags
  if [[ "${#tags[@]}" -gt 0 ]]; then
    printf '%s\n' "${tags[0]}"
  fi
}

previous_release_tag()
{
  local current_tag="$1"
  local seen_current=0
  local tags=()
  local tag=''

  if [[ "$current_tag" == "latest" ]]; then
    latest_release_tag
    return 0
  fi

  release_pep440_tags_array tags

  for tag in "${tags[@]}"; do
    if [[ "$seen_current" -eq 1 ]]; then
      printf '%s\n' "$tag"
      return 0
    fi
    if [[ "$tag" == "$current_tag" ]]; then
      seen_current=1
    fi
  done
}

release_repository_url()
{
  local remote_url

  if [[ -n "${RELEASE_REPOSITORY_URL:-}" ]]; then
    printf '%s\n' "${RELEASE_REPOSITORY_URL%/}"
    return 0
  fi

  remote_url="$(git config --get remote.origin.url)"

  if [[ "$remote_url" =~ ^https?:// ]]; then
    printf '%s\n' "${remote_url%.git}"
    return 0
  fi

  if [[ "$remote_url" =~ ^git@([^:]+):(.+)$ ]]; then
    printf 'https://%s/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
    return 0
  fi

  if [[ "$remote_url" =~ ^ssh://git@([^/]+)/(.+)$ ]]; then
    printf 'https://%s/%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
    return 0
  fi

  echo "Unsupported remote.origin.url '$remote_url'." >&2
  return 1
}
