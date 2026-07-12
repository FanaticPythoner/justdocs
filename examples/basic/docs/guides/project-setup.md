# Project Setup

Project Setup installs Justdocs into an MkDocs project and writes a local
`Justfile` for deterministic build and serve commands.

## Generator

```bash
justdocs theme-dir
justdocs projects init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs projects check --root docs-project
justdocs version
justdocs check-update
justdocs update
```

## Bootstrap Installers

```bash
curl -fsSL https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.sh | sh
```

```powershell
irm https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.ps1 | iex
```

| Variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | Platform Python launcher search order | Python executable used for the install. |
| `JUSTDOCS_INSTALL_SOURCE` | `github` | Install source: `github`, `pypi`, or `url`. |
| `JUSTDOCS_INSTALL_VERSION` | Empty | Exact PyPI version for `justdocs==<version>`. |
| `JUSTDOCS_INSTALL_REF` | Latest release tag | Explicit GitHub branch, tag, or commit archive reference. |
| `JUSTDOCS_INSTALL_SPEC` | Empty | Full pip requirement override. |
| `JUSTDOCS_INSTALL_URL` | Empty | Package URL used when `JUSTDOCS_INSTALL_SOURCE=url`. |
| `JUSTDOCS_INSTALL_ACTION` | `install` | Bootstrap action: `install` or `uninstall`. |
| `JUSTDOCS_INSTALL_ROOT` | `~/.justdocs` on POSIX; `%LOCALAPPDATA%\justdocs` on Windows | Isolated application environment and command directory. |
| `JUSTDOCS_MODIFY_PATH` | `1` | Manage the command directory in shell or user PATH configuration. |
| `JUSTDOCS_SHELL_PROFILE` | Detected POSIX shell profile | Explicit profile path for the managed PATH block. |
| `JUSTDOCS_INSTALL_DRY_RUN` | `0` | Print resolved filesystem, pip, and PATH actions without mutation. |
| `JUSTDOCS_INSTALL_TIMEOUT` | `10` | Positive finite GitHub release lookup timeout in seconds. |
| `JUSTDOCS_REPOSITORY` | `FanaticPythoner/justdocs` | GitHub repository used by `JUSTDOCS_INSTALL_SOURCE=github`. |

The installers install the latest stable GitHub release wheel into an isolated
virtualenv, expose its console command under the managed `bin` directory,
configure PATH idempotently, and execute `justdocs version` as verification.
An explicit `JUSTDOCS_INSTALL_REF` selects a branch, tag, or commit archive.

```bash
curl -fsSL https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.sh | JUSTDOCS_INSTALL_ACTION=uninstall sh
```

```powershell
$env:JUSTDOCS_INSTALL_ACTION='uninstall'; irm https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.ps1 | iex
```

| Command | Contract |
| --- | --- |
| `justdocs` | Print command help plus common project and update commands. |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs version` | Print installed package version. |
| `justdocs projects init` | Write a project-local `Justfile`. |
| `justdocs projects install` | Run the generated project `install` recipe without invoking `just`. |
| `justdocs projects check` | Run the generated project `check` recipe without invoking `just`. |
| `justdocs projects build` | Run the project check contract. |
| `justdocs projects serve` | Run the generated project `serve` recipe without invoking `just`. |
| `justdocs projects serve-clean` | Run `free-port`, then `serve`, without invoking `just`. |
| `justdocs projects free-port` | Terminate local listeners on the configured port. |
| `justdocs projects clean` | Remove MkDocs output and cache directories. |
| `justdocs projects dist-clean` | Run `clean`, then remove the configured virtualenv. |
| `justdocs check-update` | Query PyPI JSON and GitHub Releases metadata for newer versions. |
| `justdocs update` | Install the newest PyPI or GitHub release; return without reinstalling when current. |

| Option | Default | Contract |
| --- | --- | --- |
| `--root` | `.` | Directory receiving `Justfile`. |
| `--mkdocs-config` | `mkdocs.yml` | MkDocs config path used by generated recipes. |
| `--addr` | `127.0.0.1:8000` | MkDocs serve bind address. |
| `--package` | `justdocs` | Pip package spec installed by generated recipes. |
| `--extra-packages` | `pymdown-extensions==10.12` | Additional package requirements. |
| `--venv` | `.venv` | Project-local virtualenv directory. |
| `--force` | `false` | Existing `Justfile` overwrite gate. |

## Generated Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Delegate to `justdocs projects install` with stored project configuration. |
| `just check` | Run strict MkDocs build with clean output. |
| `just build` | Delegate to `justdocs projects build`. |
| `just serve` | Serve the configured MkDocs project. |
| `just serve-clean` | Free the configured port, then serve. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove MkDocs output and cache directories. |
| `just dist-clean` | Remove outputs, cache directories, and virtualenv. |

## Environment

| Variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | Current CLI interpreter | Python used to create virtualenv. |
| `JUSTDOCS_CONFIG` | Stored `mkdocs_config` | MkDocs config path. |
| `JUSTDOCS_ADDR` | Stored `addr` | MkDocs serve address. |
| `JUSTDOCS_PORT` | Port from effective address | Explicit free-port value. |
| `JUSTDOCS_PACKAGE` | Stored `package` | Pip package spec. |
| `JUSTDOCS_EXTRA_PACKAGES` | Stored `extra_packages` | Additional pip packages. |
| `JUSTDOCS_VENV` | Stored `venv` | Virtualenv directory. |

The generated Justfile starts with a bounded, versioned JSON configuration
record. CLI options override environment values, which override stored values.

## Install Safety

| Guard | Contract |
| --- | --- |
| Existing file | `ProjectJustfileExistsError` preserves existing `Justfile` unless `--force` is present. |
| Stored configuration | JSON schema, exact fields, UTF-8, type, and 64 KiB bounds are validated before recipe dispatch. |
| Package spec parsing | `ProjectJustfileInvalidPackageError` rejects invalid shell syntax and empty specs. |
| Pip options | Package tokens beginning with `-` are rejected. |
| Local source install | Shared cross-platform locking serializes installs by canonical package root. |
| Project virtualenv install | Target virtualenv locking serializes creation and pip mutation. |
| Virtualenv cleanup | Virtualenv path must be a strict descendant of the project root. |
| Missing template | `TemplateAssetError` reports absent project template assets. |
| Recipe execution | `ProjectRecipeError` reports project recipe execution invariant failure. |

## Source Repository

| Recipe | Contract |
| --- | --- |
| `just install` | Install the local package into source `.venv`. |
| `just global-install` | Install the source package into the isolated global command environment. |
| `just global-uninstall` | Remove the isolated global command environment and managed PATH entry. |
| `just theme-dir` | Print the bundled theme package path. |
| `just example-justfile` | Regenerate this example `Justfile`. |
| `just test` | Install the source virtualenv and run package tests through `.venv`. |
| `just dist` | Build sdist, wheel, Twine validation, and `SHA256SUMS.txt` through the release build script. |
| `just next-release --bump patch` | Update package version and changelog, then create the release commit and annotated tag. |
| `just example-build` | Build this example site through its generated recipe. |
| `just example-serve` | Serve this example site through its generated recipe. |
| `just check` | Run tests and strict example build. |

| Source variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_GLOBAL_PYTHON` | `JUSTDOCS_PYTHON` or `python3` | Python executable used by source global install and uninstall recipes. |

Source global recipes delegate to the platform bootstrap scripts. Bootstrap
locking serializes install-root mutations, and uninstall rejects an unowned
command path.

CLI project recipes use the current Python interpreter by default and mirror
generated project recipe contracts. `--root`, `--mkdocs-config`, `--addr`,
`--port`, `--package`, `--extra-packages`, `--venv`, and `--python` override
the corresponding `JUSTDOCS_*` environment values.

## Updates And Releases

| Surface | Contract |
| --- | --- |
| `justdocs check-update` | Compare installed version with PyPI JSON and GitHub latest release metadata. |
| `justdocs update` | Select the newest published candidate across PyPI and GitHub. |
| `justdocs update --source pypi` | Run `python -m pip install --upgrade justdocs==<version>`. |
| `justdocs update --source github` | Install the exact version-matched GitHub release wheel without invoking Git. |
| `UpdateCheckError` | Transport failure, malformed JSON, unsupported source, or unsupported version. |
| `UpdateSourceEmpty` | HTTP 404 publication state; reported as a warning when all enabled sources are unpublished. |
| `UpdateInstallError` | Downgrade request, ambiguous explicit source, or pip command failure. |

| Release surface | Contract |
| --- | --- |
| `.github/actions/build-dist/action.yml` | Composite action for sdist, wheel, Twine check, and `SHA256SUMS.txt`. |
| `.github/actions/release-assets/action.yml` | Composite action for release creation, asset purge, and asset upload. |
| `.github/workflows/ci.yml` | Python `3.10` through `3.14`, `3.13t`, `3.14t`, macOS, Windows, and distribution build. |
| `.github/workflows/release.yml` | Tag release pipeline with reproducible builds, trusted PyPI publication, provenance, GitHub release assets, and public checks. |
| `.github/workflows/latest.yml` | Moving `latest` prerelease assets for `main`. |
| `.github/workflows/pr-python-dist-comment.yml` | Trusted PR comment for the CI-built wheel, source archive, installers, and checksum manifest. |
| `.github/workflows/pr-python-dist-lifecycle.yml` | Closed-PR artifact removal and terminal managed-comment synchronization. |
| `install.sh` and `install.ps1` | Latest GitHub release bootstrap assets. |
| `pypa/gh-action-pypi-publish` | PyPI upload action using trusted publishing or `PYPI_API_TOKEN`. |
| PyPI trusted publisher | Default tokenless identity bound to `release.yml` and the `release` environment. |
| `PYPI_API_TOKEN` | Explicit publication fallback. |
| `CHANGELOG.md` | Persistent stable-release history maintained by `just next-release`. |

Stable release command:

```bash
just check
just dist
just next-release --bump patch --push
```

PyPI trusted publishing binds owner `FanaticPythoner`, repository `justdocs`, workflow
`release.yml`, environment `release`, and project `justdocs`. Missing or rejected registry
authentication fails publication before GitHub Release creation. Public checks compare PyPI and
GitHub asset digests with the reproducible local wheel and source archive.

`next-release` applies the selected SemVer bump to the package version for every release,
including the first stable tag. Release preparation writes no local artifacts. Workflow runners
generate release notes and distributions from the pushed immutable tag.
