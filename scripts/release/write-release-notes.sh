#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./release-versioning.sh
source "$script_dir/release-versioning.sh"

channel='stable'
release_tag=''
target_ref=''
target_branch=''
output_file=''

while [[ $# -gt 0 ]]; do
  case "$1" in
    --channel)
      channel="$2"
      shift 2
      ;;
    --tag)
      release_tag="$2"
      shift 2
      ;;
    --target)
      target_ref="$2"
      shift 2
      ;;
    --target-branch)
      target_branch="$2"
      shift 2
      ;;
    --output)
      output_file="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument '$1'." >&2
      exit 1
      ;;
  esac
done

if [[ -z "$release_tag" ]]; then
  echo "A release tag or channel label is required." >&2
  exit 1
fi

if [[ -z "$target_ref" ]]; then
  target_ref="$release_tag"
fi

if [[ -z "$output_file" ]]; then
  echo "An output file is required." >&2
  exit 1
fi

target_sha="$(git rev-parse "$target_ref")"
previous_tag="$(previous_release_tag "$release_tag")"
repository_url="$(release_repository_url)"
mkdir -p "$(dirname "$output_file")"

commits=()
revision="$target_sha"
if [[ -n "$previous_tag" ]]; then
  revision="${previous_tag}..${target_sha}"
fi
while IFS= read -r -d '' commit; do
  commits+=( "$commit" )
done < <(git log --reverse -z --format='%H%x1f%h%x1f%s%x1f%b' "$revision")

{
  if [[ "$channel" == 'latest' ]]; then
    echo "# justdocs latest"
    echo
    if [[ -n "$target_branch" ]]; then
      echo "- branch: \`$target_branch\`"
    fi
    echo "- target commit: [\`${target_sha}\`](${repository_url}/commit/${target_sha})"
    if [[ -n "$previous_tag" ]]; then
      echo "- base stable release: \`$previous_tag\`"
    else
      echo "- base stable release: none"
    fi
  else
    echo "# justdocs ${release_tag#v}"
    echo
    echo "- release tag: \`$release_tag\`"
    echo "- target commit: [\`${target_sha}\`](${repository_url}/commit/${target_sha})"
    if [[ -n "$previous_tag" ]]; then
      echo "- previous release: \`$previous_tag\`"
    else
      echo "- previous release: none"
    fi
  fi
  echo
  echo "## Included commits"
  echo

  if [[ ${#commits[@]} -eq 0 ]]; then
    echo "- No commits beyond the previous release boundary."
  else
    for commit in "${commits[@]}"; do
      commit="${commit#$'\n'}"
      full_sha="${commit%%$'\x1f'*}"
      if [[ -z "$full_sha" ]]; then
        continue
      fi
      remainder="${commit#*$'\x1f'}"
      short_sha="${remainder%%$'\x1f'*}"
      remainder="${remainder#*$'\x1f'}"
      subject="${remainder%%$'\x1f'*}"
      body="${remainder#*$'\x1f'}"
      printf -- "- [\`%s\`](%s/commit/%s) %s\n" "$short_sha" "$repository_url" "$full_sha" "$subject"
      if [[ -n "$body" ]]; then
        while IFS= read -r body_line; do
          printf '  > %s\n' "$body_line"
        done <<<"$body"
      fi
    done
  fi
} > "$output_file"
