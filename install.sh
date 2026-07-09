#!/bin/sh
set -eu

package=justdocs
repository=${JUSTDOCS_REPOSITORY:-FanaticPythoner/justdocs}
source=${JUSTDOCS_INSTALL_SOURCE:-github}
version=${JUSTDOCS_INSTALL_VERSION:-}
ref=${JUSTDOCS_INSTALL_REF:-main}
spec=${JUSTDOCS_INSTALL_SPEC:-}
dry_run=${JUSTDOCS_INSTALL_DRY_RUN:-0}
python=${JUSTDOCS_PYTHON:-}

if [ -z "$python" ]; then
    if command -v python3 >/dev/null 2>&1; then
        python=python3
    elif command -v python >/dev/null 2>&1; then
        python=python
    else
        printf '%s\n' "Python 3.10+ is required." >&2
        exit 1
    fi
fi

if ! "$python" - <<'PY'
import sys

raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
    printf '%s\n' "Python 3.10+ is required." >&2
    exit 1
fi

if [ -z "$spec" ]; then
    case "$source" in
        pypi)
            if [ -n "$version" ]; then
                spec="${package}==${version}"
            else
                spec=$package
            fi
            ;;
        github)
            spec="https://github.com/${repository}/archive/${ref}.tar.gz"
            ;;
        url)
            spec=${JUSTDOCS_INSTALL_URL:?"JUSTDOCS_INSTALL_URL must be set."}
            ;;
        *)
            printf '%s\n' "unsupported JUSTDOCS_INSTALL_SOURCE '$source': expected pypi, github, or url" >&2
            exit 1
            ;;
    esac
fi

case "$dry_run" in
    1 | true | TRUE | yes | YES)
        printf '%s\n' "$python -m pip install --user --upgrade $spec"
        exit 0
        ;;
esac

if ! "$python" -m pip --version >/dev/null 2>&1; then
    "$python" -m ensurepip --user >/dev/null
fi

"$python" -m pip install --user --upgrade "$spec"

scripts_dir=$("$python" - <<'PY'
import os
import sysconfig

print(sysconfig.get_path("scripts", scheme=f"{os.name}_user") or "")
PY
)

if [ -z "$scripts_dir" ]; then
    printf '%s\n' "Python user scripts directory is unavailable." >&2
    exit 1
fi

if ! command -v justdocs >/dev/null 2>&1; then
    printf '%s\n' "justdocs install completed, but the command is not on PATH." >&2
    printf '%s\n' "Add Python user scripts directory to PATH: $scripts_dir" >&2
    exit 1
fi

resolved=$(command -v justdocs)
case "$resolved" in
    "$scripts_dir"/*)
        ;;
    *)
        printf '%s\n' "justdocs resolves outside Python user scripts: $resolved" >&2
        printf '%s\n' "Expected scripts directory: $scripts_dir" >&2
        exit 1
        ;;
esac

printf '%s\n' "installed $resolved"
justdocs version
