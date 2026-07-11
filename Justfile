set shell := ["bash", "-cu"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

python := env_var_or_default("JUSTDOCS_PYTHON", if os() == "windows" { "python" } else { "python3" })
global_python := env_var_or_default("JUSTDOCS_GLOBAL_PYTHON", python)
example_addr := env_var_or_default("JUSTDOCS_EXAMPLE_ADDR", "127.0.0.1:8020")
venv_python := ".venv/bin/python"
venv_mkdocs := ".venv/bin/mkdocs"

default:
    @just --list

install:
    @test -x {{venv_python}} || {{python}} -m venv .venv
    @{{venv_python}} -m pip install --upgrade pip
    @package_spec="."; lock_dir="${TMPDIR:-/tmp}/justdocs-install-locks"; mkdir -p "$lock_dir"; package_root="$(pwd -P)"; lock_id="$(printf "%s" "$package_root" | cksum | awk '{print $1}')"; flock "$lock_dir/$lock_id.lock" {{venv_python}} -m pip install $package_spec pymdown-extensions==10.12

global-install:
    @{{global_python}} -c "import sys; sys.path.insert(0, '.'); from justdocs.global_cli import main; raise SystemExit(main(['install', '--project-root', '.']))"

global-uninstall:
    @{{global_python}} -c "import sys; sys.path.insert(0, '.'); from justdocs.global_cli import main; raise SystemExit(main(['uninstall', '--project-root', '.']))"

theme-dir:
    @PYTHONPATH=. {{python}} -m justdocs.cli theme-dir

example-justfile: install
    @PYTHONPATH=. {{venv_python}} -m justdocs.cli projects init --root examples/basic --package ../.. --addr {{example_addr}} --force

test: install
    @PYTHONPATH=. {{venv_python}} -m unittest discover -s tests

dist: install
    @PYTHON_BIN={{venv_python}} bash scripts/release/build-python-package.sh

example-build: example-justfile
    @cd examples/basic && PATH="../../.venv/bin:$PATH" just check

example-serve: example-justfile
    @cd examples/basic && PATH="../../.venv/bin:$PATH" just serve

check: test
    just example-build
