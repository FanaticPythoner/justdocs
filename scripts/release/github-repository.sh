#!/usr/bin/env bash

release_validate_boolean()
{
  local name="${1:-}"
  local value="${2:-}"

  if [[ $# -ne 2 || "$value" != "true" && "$value" != "false" ]]; then
    echo "invalid $name '$value': expected true or false" >&2
    return 2
  fi
}

release_validate_tag()
{
  local release_tag="${1:-}"

  if [[ $# -ne 1 || -z "$release_tag" || "$release_tag" == -* ]] || \
    ! git check-ref-format "refs/tags/$release_tag" >/dev/null; then
    echo "invalid release_tag '$release_tag'" >&2
    return 2
  fi
}

release_validate_name()
{
  local release_name="${1:-}"

  if [[ $# -ne 1 || -z "$release_name" || "$release_name" == *[$'\x01'-$'\x1f'$'\x7f']* ]]; then
    echo 'invalid release_name: expected nonempty text without control characters' >&2
    return 2
  fi
}

release_github_repository()
{
  local repository="${GITHUB_REPOSITORY:-}"
  local owner="${repository%%/*}"
  local name="${repository#*/}"

  if [[ -z "$repository" || "$owner" == "$repository" || "$name" == */* ]] || \
    ! [[ "$owner" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || \
    [[ "$owner" == *- || "$owner" == *--* ]] || \
    ! [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || \
    [[ ${#name} -gt 100 || "$name" == "." || "$name" == ".." ]]; then
    echo "invalid GITHUB_REPOSITORY '$repository': expected OWNER/REPOSITORY" >&2
    return 2
  fi
  printf '%s\n' "$repository"
}
