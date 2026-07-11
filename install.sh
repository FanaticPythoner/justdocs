#!/bin/sh
set -eu

package=justdocs
repository=${JUSTDOCS_REPOSITORY:-FanaticPythoner/justdocs}
source=${JUSTDOCS_INSTALL_SOURCE:-github}
version=${JUSTDOCS_INSTALL_VERSION:-}
ref=${JUSTDOCS_INSTALL_REF:-}
spec=${JUSTDOCS_INSTALL_SPEC:-}
action=${JUSTDOCS_INSTALL_ACTION:-install}
dry_run=${JUSTDOCS_INSTALL_DRY_RUN:-0}
modify_path=${JUSTDOCS_MODIFY_PATH:-1}
timeout=${JUSTDOCS_INSTALL_TIMEOUT:-10}
python=${JUSTDOCS_PYTHON:-}
install_root=${JUSTDOCS_INSTALL_ROOT:-${HOME:?HOME must be set}/.justdocs}
bin_dir=$install_root/bin
venv_dir=$install_root/venv
venv_python=$venv_dir/bin/python
venv_command=$venv_dir/bin/justdocs
command_path=$bin_dir/justdocs
managed_file=$install_root/.justdocs-managed
lock_dir=$install_root.install-lock
profile=${JUSTDOCS_SHELL_PROFILE:-}
profile_kind=sh
path_start='# >>> justdocs PATH >>>'
path_end='# <<< justdocs PATH <<<'

is_true() {
    case "$1" in
        1 | true | TRUE | yes | YES) return 0 ;;
        *) return 1 ;;
    esac
}

validate_boolean() {
    name=$1
    value=$2
    case "$value" in
        0 | false | FALSE | no | NO | 1 | true | TRUE | yes | YES) ;;
        *)
            printf '%s\n' "invalid $name '$value': expected 0, 1, false, true, no, or yes" >&2
            exit 1
            ;;
    esac
}

resolve_python() {
    if [ -n "$python" ]; then
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python=python3
    elif command -v python >/dev/null 2>&1; then
        python=python
    else
        printf '%s\n' 'Python 3.10+ is required.' >&2
        exit 1
    fi
}

validate_python() {
    if ! "$python" - <<'PY'
import sys

raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
        printf '%s\n' 'Python 3.10+ is required.' >&2
        exit 1
    fi
}

validate_install_root() {
    install_root=$(JUSTDOCS_ROOT=$install_root "$python" - <<'PY'
import os
from pathlib import Path

root = Path(os.environ["JUSTDOCS_ROOT"]).expanduser().resolve()
home = Path.home().resolve()
if root == Path(root.anchor) or root == home:
    raise SystemExit(f"unsafe JUSTDOCS_INSTALL_ROOT: {root}")
print(root)
PY
    )
    bin_dir=$install_root/bin
    venv_dir=$install_root/venv
    venv_python=$venv_dir/bin/python
    venv_command=$venv_dir/bin/justdocs
    command_path=$bin_dir/justdocs
    managed_file=$install_root/.justdocs-managed
    lock_dir=$install_root.install-lock
}

resolve_spec() {
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
                if [ -z "$ref" ]; then
                    spec=$("$python" - "$repository" "$timeout" "$package" <<'PY'
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

repository, raw_timeout, package = sys.argv[1:]
if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
    raise SystemExit(f"invalid JUSTDOCS_REPOSITORY: {repository}")
try:
    timeout = float(raw_timeout)
except ValueError as error:
    raise SystemExit(f"invalid JUSTDOCS_INSTALL_TIMEOUT: {raw_timeout}") from error
if not math.isfinite(timeout) or timeout <= 0:
    raise SystemExit(f"invalid JUSTDOCS_INSTALL_TIMEOUT: {raw_timeout}")
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "justdocs-installer",
    "X-GitHub-Api-Version": "2022-11-28",
}
token = os.environ.get("GITHUB_TOKEN")
if token:
    headers["Authorization"] = f"Bearer {token}"
url = f"https://api.github.com/repos/{repository}/releases/latest"
request = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
except (TimeoutError, urllib.error.URLError, OSError) as error:
    raise SystemExit(f"GitHub release lookup failed: {error}") from error
if len(payload) > 2 * 1024 * 1024:
    raise SystemExit("GitHub release lookup failed: response exceeds 2097152 bytes")
try:
    metadata = json.loads(payload.decode("utf-8"))
except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise SystemExit("GitHub release lookup failed: invalid JSON response") from error
tag = metadata.get("tag_name") if isinstance(metadata, dict) else None
if not isinstance(tag, str) or not tag or any(character.isspace() for character in tag):
    raise SystemExit("GitHub release lookup failed: tag_name missing or invalid")
assets = metadata.get("assets")
if not isinstance(assets, list):
    raise SystemExit("GitHub release lookup failed: assets list missing")
matches = [
    asset.get("browser_download_url")
    for asset in assets
    if isinstance(asset, dict)
    and isinstance(asset.get("name"), str)
    and asset["name"].startswith(f"{package}-")
    and asset["name"].endswith("-py3-none-any.whl")
    and isinstance(asset.get("browser_download_url"), str)
    and asset["browser_download_url"].endswith(f"/{asset['name']}")
]
if len(matches) != 1 or not matches[0].startswith("https://github.com/"):
    raise SystemExit("GitHub release lookup failed: expected one universal wheel asset")
print(matches[0])
PY
                    )
                else
                    spec="https://github.com/${repository}/archive/${ref}.tar.gz"
                fi
                ;;
            url) spec=${JUSTDOCS_INSTALL_URL:?'JUSTDOCS_INSTALL_URL must be set.'} ;;
            *)
                printf '%s\n' "unsupported JUSTDOCS_INSTALL_SOURCE '$source': expected pypi, github, or url" >&2
                exit 1
                ;;
        esac
    fi
    case "$spec" in
        -*)
            printf '%s\n' "invalid JUSTDOCS_INSTALL_SPEC: pip option rejected: $spec" >&2
            exit 1
            ;;
    esac
}

resolve_profile() {
    shell_name=${SHELL:-}
    shell_name=${shell_name##*/}
    if [ "$shell_name" = fish ]; then
        profile_kind=fish
    fi
    if [ -n "$profile" ]; then
        return
    fi
    case "$shell_name" in
        fish) profile=$HOME/.config/fish/config.fish ;;
        zsh) profile=$HOME/.zshrc ;;
        bash) profile=$HOME/.bashrc ;;
        *) profile=$HOME/.profile ;;
    esac
}

acquire_lock() {
    mkdir -p "$(dirname "$install_root")"
    lock_acquired=0
    if mkdir "$lock_dir" 2>/dev/null; then
        lock_acquired=1
    else
        lock_pid=''
        if [ -f "$lock_dir/pid" ]; then
            lock_pid=$(cat "$lock_dir/pid")
        fi
        case "$lock_pid" in
            '' | *[!0-9]*) ;;
            *)
                if ! kill -0 "$lock_pid" 2>/dev/null; then
                    rm "$lock_dir/pid"
                    rmdir "$lock_dir"
                    mkdir "$lock_dir"
                    lock_acquired=1
                fi
                ;;
        esac
    fi
    if [ "$lock_acquired" -ne 1 ]; then
        printf '%s\n' "justdocs installer lock is held: $lock_dir" >&2
        exit 1
    fi
    printf '%s\n' "$$" > "$lock_dir/pid"
    trap 'rm "$lock_dir/pid"; rmdir "$lock_dir"' EXIT HUP INT TERM
}

claim_install_root() {
    if [ -e "$install_root" ] && [ ! -d "$install_root" ]; then
        printf '%s\n' "install root is not a directory: $install_root" >&2
        exit 1
    fi
    if [ -d "$install_root" ] && [ ! -f "$managed_file" ] && [ -n "$(ls -A "$install_root")" ]; then
        printf '%s\n' "refusing to use unmanaged nonempty install root: $install_root" >&2
        exit 1
    fi
    mkdir -p "$install_root"
    if [ -L "$managed_file" ]; then
        printf '%s\n' "invalid install ownership marker symlink: $managed_file" >&2
        exit 1
    fi
    if [ -f "$managed_file" ] && [ "$(cat "$managed_file")" != 'justdocs-managed-v1' ]; then
        printf '%s\n' "invalid install ownership marker: $managed_file" >&2
        exit 1
    fi
    printf '%s\n' 'justdocs-managed-v1' > "$managed_file"
}

verify_owned_command() {
    if [ -e "$command_path" ] || [ -L "$command_path" ]; then
        if [ ! -L "$command_path" ] || [ "$(readlink "$command_path")" != "$venv_command" ]; then
            printf '%s\n' "refusing to modify unowned command: $command_path" >&2
            exit 1
        fi
    fi
}

release_lock() {
    rm "$lock_dir/pid"
    rmdir "$lock_dir"
    trap - EXIT HUP INT TERM
}

edit_profile() {
    mode=$1
    JUSTDOCS_PROFILE=$profile \
    JUSTDOCS_BIN_DIR=$bin_dir \
    JUSTDOCS_PATH_START=$path_start \
    JUSTDOCS_PATH_END=$path_end \
    JUSTDOCS_PROFILE_KIND=$profile_kind \
    "$python" - "$mode" <<'PY'
import os
import shlex
import sys
from pathlib import Path

profile = Path(os.environ["JUSTDOCS_PROFILE"]).expanduser()
start = os.environ["JUSTDOCS_PATH_START"]
end = os.environ["JUSTDOCS_PATH_END"]
mode = sys.argv[1]
text = profile.read_text(encoding="utf-8") if profile.exists() else ""
lines = text.splitlines()
filtered: list[str] = []
inside = False
for line in lines:
    if line == start:
        if inside:
            raise SystemExit(f"nested justdocs PATH block in {profile}")
        inside = True
        continue
    if line == end:
        if not inside:
            raise SystemExit(f"unmatched justdocs PATH block in {profile}")
        inside = False
        continue
    if not inside:
        filtered.append(line)
if inside:
    raise SystemExit(f"unterminated justdocs PATH block in {profile}")
while filtered and filtered[-1] == "":
    filtered.pop()
if mode == "add":
    bin_dir = os.environ["JUSTDOCS_BIN_DIR"]
    if os.environ["JUSTDOCS_PROFILE_KIND"] == "fish":
        shell_line = f"fish_add_path --global {shlex.quote(bin_dir)}"
    else:
        shell_line = f'export PATH={shlex.quote(bin_dir)}:"$PATH"'
    filtered.extend(("", start, shell_line, end))
elif mode != "remove":
    raise SystemExit(f"unsupported profile edit mode: {mode}")
profile.parent.mkdir(parents=True, exist_ok=True)
payload = "\n".join(filtered)
profile.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
PY
}

install_package() {
    resolve_spec
    if is_true "$dry_run"; then
        printf '%s\n' "$python -m venv $venv_dir"
        printf '%s\n' "$venv_python -m pip install --upgrade $spec"
        printf '%s\n' "link $command_path -> $venv_command"
        if is_true "$modify_path"; then
            printf '%s\n' "add $bin_dir to PATH in $profile"
        fi
        return
    fi
    acquire_lock
    claim_install_root
    mkdir -p "$bin_dir"
    verify_owned_command
    if [ ! -x "$venv_python" ]; then
        "$python" -m venv "$venv_dir"
    fi
    "$venv_python" -m pip install --upgrade "$spec"
    if [ ! -x "$venv_command" ]; then
        printf '%s\n' "installed package missing console command: $venv_command" >&2
        exit 1
    fi
    temp_link=$command_path.tmp.$$
    rm -f "$temp_link"
    ln -s "$venv_command" "$temp_link"
    mv -f "$temp_link" "$command_path"
    PATH=$bin_dir:$PATH "$command_path" version >/dev/null
    if is_true "$modify_path"; then
        edit_profile add
    fi
    release_lock
    printf '%s\n' "installed $command_path"
    "$command_path" version
    if is_true "$modify_path"; then
        printf '%s\n' "PATH configured in $profile; restart the terminal to load it."
    fi
}

uninstall_package() {
    if is_true "$dry_run"; then
        printf '%s\n' "remove $install_root"
        if is_true "$modify_path"; then
            printf '%s\n' "remove $bin_dir from PATH in $profile"
        fi
        return
    fi
    acquire_lock
    if [ -L "$managed_file" ]; then
        printf '%s\n' "invalid install ownership marker symlink: $managed_file" >&2
        exit 1
    fi
    if [ -e "$install_root" ] && [ ! -f "$managed_file" ]; then
        printf '%s\n' "refusing to remove unmanaged install root: $install_root" >&2
        exit 1
    fi
    if [ -f "$managed_file" ] && [ "$(cat "$managed_file")" != 'justdocs-managed-v1' ]; then
        printf '%s\n' "invalid install ownership marker: $managed_file" >&2
        exit 1
    fi
    if [ -d "$install_root" ]; then
        verify_owned_command
        rm -rf "$install_root"
    fi
    if is_true "$modify_path"; then
        edit_profile remove
    fi
    release_lock
    printf '%s\n' "uninstalled $package"
}

resolve_python
validate_boolean JUSTDOCS_INSTALL_DRY_RUN "$dry_run"
validate_boolean JUSTDOCS_MODIFY_PATH "$modify_path"
validate_python
validate_install_root
if is_true "$modify_path"; then
    resolve_profile
fi

case "$action" in
    install) install_package ;;
    uninstall) uninstall_package ;;
    *)
        printf '%s\n' "unsupported JUSTDOCS_INSTALL_ACTION '$action': expected install or uninstall" >&2
        exit 1
        ;;
esac
