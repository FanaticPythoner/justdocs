# Project Setup

Project Setup installs Justdocs into an MkDocs project and writes a local
`Justfile` for deterministic build and serve commands.

## Generator

```bash
justdocs theme-dir
justdocs init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs project init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs project check --root docs-project
justdocs version --check
justdocs self check-update
justdocs self update
```

## Bootstrap Installers

```bash
curl -fsSL https://raw.githubusercontent.com/FanaticPythoner/justdocs/main/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/FanaticPythoner/justdocs/main/install.ps1 | iex
```

| Variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | Platform Python launcher search order | Python executable used for the install. |
| `JUSTDOCS_INSTALL_SOURCE` | `github` | Install source: `github`, `pypi`, or `url`. |
| `JUSTDOCS_INSTALL_VERSION` | Empty | Exact PyPI version for `justdocs==<version>`. |
| `JUSTDOCS_INSTALL_REF` | `main` | GitHub branch, tag, or commit archive reference. |
| `JUSTDOCS_INSTALL_SPEC` | Empty | Full pip requirement override. |
| `JUSTDOCS_INSTALL_URL` | Empty | Package URL used when `JUSTDOCS_INSTALL_SOURCE=url`. |
| `JUSTDOCS_INSTALL_DRY_RUN` | `0` | Print the resolved pip install command and exit. |
| `JUSTDOCS_REPOSITORY` | `FanaticPythoner/justdocs` | GitHub repository used by `JUSTDOCS_INSTALL_SOURCE=github`. |

The installers run `python -m pip install --user --upgrade` and verify that
`justdocs` resolves from the selected interpreter's user script directory.
Missing `PATH` entries and conflicting `justdocs` commands are fatal.

| Command | Contract |
| --- | --- |
| `justdocs` | Print command help plus common project and update commands. |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs version` | Print installed package version. |
| `justdocs version --check` | Print current version and newest available PyPI or GitHub release version. |
| `justdocs init` | Write a project-local `Justfile`. |
| `justdocs project init` | Namespaced alias for `justdocs init`. |
| `justdocs projects init` | Plural alias for `justdocs project init`. |
| `justdocs project install` | Run the generated project `install` recipe without invoking `just`. |
| `justdocs project check` | Run the generated project `check` recipe without invoking `just`. |
| `justdocs project build` | Alias for `justdocs project check`. |
| `justdocs project serve` | Run the generated project `serve` recipe without invoking `just`. |
| `justdocs project serve-clean` | Run `free-port`, then `serve`, without invoking `just`. |
| `justdocs project free-port` | Terminate local listeners on the configured port. |
| `justdocs project clean` | Remove MkDocs output and cache directories. |
| `justdocs project dist-clean` | Run `clean`, then remove the configured virtualenv. |
| `justdocs self check-update` | Query PyPI JSON and GitHub Releases metadata for newer versions. |
| `justdocs self update` | Upgrade the installed package from PyPI or a GitHub release tag. |

| Option | Default | Contract |
| --- | --- | --- |
| `--root` | `.` | Directory receiving `Justfile`. |
| `--mkdocs-config` | `mkdocs.yml` | MkDocs config path used by generated recipes. |
| `--addr` | `127.0.0.1:8000` | MkDocs serve bind address. |
| `--package` | `justdocs` | Pip package spec installed by generated recipes. |
| `--force` | `false` | Existing `Justfile` overwrite gate. |

## Generated Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Create virtualenv, upgrade pip, install package spec, and install extra packages. |
| `just check` | Run strict MkDocs build with clean output. |
| `just build` | Alias for `check`. |
| `just serve` | Serve the configured MkDocs project. |
| `just serve-clean` | Free the configured port, then serve. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove MkDocs output and cache directories. |
| `just dist-clean` | Remove outputs, cache directories, and virtualenv. |

## Environment

| Variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | `python3` | Python used to create virtualenv. |
| `JUSTDOCS_CONFIG` | generator config path | MkDocs config path. |
| `JUSTDOCS_ADDR` | generator address | MkDocs serve address. |
| `JUSTDOCS_PORT` | port from address | Port passed to `lsof -t -i`. |
| `JUSTDOCS_PACKAGE` | generator package spec | Pip package spec. |
| `JUSTDOCS_EXTRA_PACKAGES` | `pymdown-extensions==10.12` | Additional pip packages. |
| `JUSTDOCS_VENV` | `.venv` | Virtualenv directory. |
| `JUSTDOCS_VENV_PYTHON` | `.venv/bin/python` | Virtualenv Python executable. |
| `JUSTDOCS_VENV_MKDOCS` | `.venv/bin/mkdocs` | Virtualenv MkDocs executable. |

## Install Safety

| Guard | Contract |
| --- | --- |
| Existing file | `ProjectJustfileExistsError` preserves existing `Justfile` unless `--force` is present. |
| Package spec parsing | `ProjectJustfileInvalidPackageError` rejects invalid shell syntax and empty specs. |
| Editable install | `-e`, `--editable`, and `--editable=<path>` are rejected. |
| Local source install | `flock` serializes installs by canonical package root. |
| Missing template | `TemplateAssetError` reports absent project template assets. |
| Recipe execution | `ProjectRecipeError` reports project recipe execution invariant failure. |

## Source Repository

| Recipe | Contract |
| --- | --- |
| `just install` | Install the local package into source `.venv`. |
| `just global-install` | Install the source package into the selected Python user site and verify `justdocs` resolves on `PATH`. |
| `just install-global` | Alias for `global-install`. |
| `just global-uninstall` | Remove `justdocs` from the selected Python environment and verify user-script files are absent. |
| `just uninstall-global` | Alias for `global-uninstall`. |
| `just theme-dir` | Print the bundled theme package path. |
| `just example-justfile` | Regenerate this example `Justfile`. |
| `just test` | Install the source virtualenv and run package tests through `.venv`. |
| `just dist` | Build sdist, wheel, Twine validation, and `SHA256SUMS.txt` through the release build script. |
| `just example-build` | Build this example site through its generated recipe. |
| `just example-serve` | Serve this example site through its generated recipe. |
| `just check` | Run tests and strict example build. |

| Source variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_GLOBAL_PYTHON` | `JUSTDOCS_PYTHON` or `python3` | Python executable used by source global install and uninstall recipes. |

Global installs use the current interpreter's user script directory from
`sysconfig`. `global install failed` reports a missing console script, missing
`PATH` entry, or an existing `justdocs` command from a different location.

CLI project recipes use the current Python interpreter by default and mirror
generated project recipe contracts. `--root`, `--mkdocs-config`, `--addr`,
`--port`, `--package`, `--extra-packages`, `--venv`, and `--python` override
the corresponding `JUSTDOCS_*` environment values.

## Updates And Releases

| Surface | Contract |
| --- | --- |
| `justdocs self check-update` | Compare installed version with PyPI JSON and GitHub latest release metadata. |
| `justdocs self update --source pypi` | Run `python -m pip install --upgrade justdocs==<version>`. |
| `justdocs self update --source github` | Run `python -m pip install --upgrade justdocs @ git+https://github.com/<owner>/<repo>.git@v<version>`. |
| `UpdateCheckError` | Metadata source failure, malformed JSON, unsupported source, or unsupported version. |
| `UpdateInstallError` | Pip update command failure. |

| Release surface | Contract |
| --- | --- |
| `.github/actions/build-dist/action.yml` | Composite action for sdist, wheel, Twine check, and `SHA256SUMS.txt`. |
| `.github/actions/release-assets/action.yml` | Composite action for release creation, asset purge, and asset upload. |
| `.github/workflows/ci.yml` | Python `3.10` through `3.14`, `3.13t`, `3.14t`, macOS, Windows, and distribution build. |
| `.github/workflows/release.yml` | Tag release pipeline with tests, build, PyPI publish gate, GitHub release assets, and PyPI visibility check. |
| `.github/workflows/latest.yml` | Moving `latest` prerelease assets for `main`. |
| `install.sh` and `install.ps1` | GitHub release assets plus raw-repository bootstrap installers. |
| `pypa/gh-action-pypi-publish` | PyPI upload action used when `PYPI_API_TOKEN` is present. |
