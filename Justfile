set shell := ["bash", "-cu"]

python := env_var_or_default("JUSTDOCS_PYTHON", "python3")
example_addr := env_var_or_default("JUSTDOCS_EXAMPLE_ADDR", "127.0.0.1:8020")
venv_python := ".venv/bin/python"
venv_mkdocs := ".venv/bin/mkdocs"

default:
    @just --list

install:
    @test -x {{venv_python}} || {{python}} -m venv .venv
    @{{venv_python}} -m pip install --upgrade pip
    @package_spec="."; lock_dir="${TMPDIR:-/tmp}/justdocs-install-locks"; mkdir -p "$lock_dir"; package_root="$(pwd -P)"; lock_id="$(printf "%s" "$package_root" | cksum | awk '{print $1}')"; flock "$lock_dir/$lock_id.lock" {{venv_python}} -m pip install $package_spec pymdown-extensions==10.12

theme-dir:
    @PYTHONPATH=. {{python}} -m justdocs.cli theme-dir

example-justfile: install
    @PYTHONPATH=. {{venv_python}} -m justdocs.cli init --root examples/basic --package ../.. --addr {{example_addr}} --force

test:
    @PYTHONPATH=. {{python}} -m unittest discover -s tests

example-build: example-justfile
    @cd examples/basic && just check

example-serve: example-justfile
    @cd examples/basic && just serve

check: install
    just test
    just example-build
