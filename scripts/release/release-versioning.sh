#!/usr/bin/env bash
set -euo pipefail

release_semver_tag_pattern='^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$'

release_semver_tags_array()
{
  local output_name="$1"
  local -n output_ref="$output_name"
  local tag=''

  output_ref=()
  while read -r tag; do
    if [[ "$tag" =~ $release_semver_tag_pattern ]]; then
      output_ref+=( "$tag" )
    fi
  done < <(git tag --sort=-v:refname)
}

latest_release_tag()
{
  local tags=()
  release_semver_tags_array tags
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

  release_semver_tags_array tags

  for tag in "${tags[@]}"; do
    if [[ "$current_tag" == "latest" ]]; then
      printf '%s\n' "$tag"
      return 0
    fi
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
