#!/usr/bin/env bash
set -euo pipefail

release_python_bin()
{
  local candidate="${PYTHON_BIN:-python3}"

  if ! command -v "$candidate" >/dev/null 2>&1; then
    echo "Python executable not found: $candidate" >&2
    return 127
  fi
  printf '%s\n' "$candidate"
}

release_select_pep440_tag()
{
  local mode="$1"
  local current_tag="${2:-}"
  local python_bin=''

  python_bin="$(release_python_bin)" || return
  "$python_bin" - "$mode" "$current_tag" <<'PY'
import subprocess
import sys

from packaging.version import InvalidVersion, Version

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required.")

mode, current_tag = sys.argv[1:]
if mode not in {"latest", "previous"}:
    raise SystemExit(f"unsupported release tag selection mode: {mode}")

try:
    completed = subprocess.run(
        ("git", "tag", "--list", "v*"),
        check=True,
        capture_output=True,
        text=True,
    )
except OSError as error:
    raise SystemExit(f"git tag query failed: {error}") from error
except subprocess.CalledProcessError as error:
    detail = error.stderr.strip()
    message = f"git tag query failed with exit code {error.returncode}"
    if detail:
        message = f"{message}: {detail}"
    raise SystemExit(message) from error

versions = []
for tag in completed.stdout.splitlines():
    try:
        versions.append((Version(tag[1:]), tag))
    except InvalidVersion:
        continue

ordered_versions = sorted(
    versions,
    key=lambda item: (item[0], item[1]),
    reverse=True,
)
ordered = [tag for _, tag in ordered_versions]

selected = None
if mode == "latest" or current_tag == "latest":
    if ordered:
        selected = ordered[0]
else:
    try:
        current_version = Version(current_tag[1:])
    except InvalidVersion:
        current_version = None
    if current_tag in ordered and current_version is not None:
        selected = next(
            (
                tag
                for version, tag in ordered_versions
                if version < current_version
            ),
            None,
        )

if selected is not None:
    print(selected)
PY
}

latest_release_tag()
{
  release_select_pep440_tag latest
}

previous_release_tag()
{
  release_select_pep440_tag previous "$1"
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
