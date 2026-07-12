# Reference

## Package

| Surface | Value |
| --- | --- |
| Name | `justdocs` |
| Version source | `[project].version` in `pyproject.toml` |
| Python | `>=3.10` |
| Dependency | `mkdocs>=1.6,<3`, `packaging>=24` |
| Console script | `justdocs = justdocs.cli:main` |
| Theme entry point | `justdocs = justdocs.theme` |
| Plugin entry point | `justdocs-linker = justdocs.plugins:JustdocsLinkerPlugin` |

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

Installers place the latest stable GitHub release wheel in a dedicated
virtualenv, expose the console command under the managed `bin` directory,
configure PATH, and execute `justdocs version`.

## Required Assets

| Asset | Contract |
| --- | --- |
| `404.html` | Static not-found template. |
| `base.html` | Full MkDocs page template. |
| `main.html` | Template extending `base.html`. |
| `mkdocs_theme.yml` | MkDocs theme metadata. |
| `assets/css/theme.css` | Theme layout and component styles. |
| `assets/css/highlightjs.min.css` | Highlight.js style. |
| `assets/css/highlightjs-copy.min.css` | Copy button style. |
| `assets/js/theme.js` | Theme runtime. |
| `assets/js/highlightjs.min.js` | Highlight.js runtime. |
| `assets/js/highlightjs-copy.min.js` | Copy button plugin runtime. |
| `assets/js/mermaid.min.js` | Mermaid runtime. |
| `assets/js/mermaid.LICENSE.txt` | Mermaid MIT license text. |

## Python API

| Symbol | Contract |
| --- | --- |
| `theme_dir()` | Validate required theme files and return the theme directory path. |
| `project_justfile_template()` | Validate template files and return `project.Justfile`. |
| `ProjectJustfileConfig` | Store generated project recipe configuration. |
| `render_project_justfile()` | Render the packaged project recipe template. |
| `write_project_justfile()` | Create the project root and write `Justfile`. |
| `read_project_justfile_config()` | Parse and validate the generated Justfile JSON configuration record. |
| `ProjectRecipeConfig` | Store project recipe execution inputs. |
| `ProjectRecipeError` | Report project recipe execution invariant failure. |
| `GlobalCliError` | Report global console-script install or uninstall invariant failure. |
| `UpdateCheckError` | Report update metadata resolution failure. |
| `UpdateSourceEmpty` | Report an update source without a published release. |
| `UpdateInstallError` | Report update installation failure. |
| `JustdocsLinkerPlugin` | Insert deterministic cross-page links before Markdown rendering. |

## CLI

| Command | Contract |
| --- | --- |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs projects init` | Write a project-local `Justfile` from the packaged template. |
| `justdocs projects install` | Run the generated project `install` recipe without invoking `just`. |
| `justdocs projects check` | Run the generated project `check` recipe without invoking `just`. |
| `justdocs projects build` | Run the project check contract. |
| `justdocs projects serve` | Run the generated project `serve` recipe without invoking `just`. |
| `justdocs projects serve-clean` | Run `free-port`, then `serve`, without invoking `just`. |
| `justdocs projects free-port` | Terminate local listeners on the configured port. |
| `justdocs projects clean` | Remove MkDocs output and cache directories. |
| `justdocs projects dist-clean` | Run `clean`, then remove the configured virtualenv. |
| `justdocs check-update` | Query PyPI JSON and GitHub Releases metadata for newer versions. |
| `justdocs update` | Upgrade the installed package from PyPI or a GitHub release tag. |

## Release Pipeline

| Surface | Contract |
| --- | --- |
| `.github/actions/build-dist/action.yml` | Build sdist, wheel, Twine check, and `SHA256SUMS.txt`. |
| `.github/actions/release-assets/action.yml` | Create GitHub releases and upload distribution assets. |
| `.github/workflows/release.yml` | Publish reproducible distributions through PyPI trusted publishing or `PYPI_API_TOKEN`, attest provenance, create the GitHub Release, and verify both public surfaces. |
| PyPI trusted publisher | Default tokenless identity bound to `release.yml` and the `release` environment. |
| `PYPI_API_TOKEN` | Explicit publication fallback. |
| `.github/workflows/latest.yml` | Maintain a moving `latest` prerelease from `main`. |
| `.github/workflows/pr-python-dist-comment.yml` | Publish a trusted PR link to CI-built Python release artifacts. |
| `CHANGELOG.md` | Persist stable release history generated by `just next-release`. |

| Stable release invariant | Enforcement |
| --- | --- |
| Version | `pyproject.toml` version equals annotated `vX.Y.Z` tag. |
| Changelog | `CHANGELOG.md` contains the dated version entry and chronological commit boundary. |
| PyPI | Wheel and source archive names, sizes, and SHA-256 digests match built artifacts. |
| GitHub | Published release tag, title, notes, latest binding, and every asset digest match. |
| PR package | CI artifact contains wheel, source archive, installers, and `SHA256SUMS.txt`; trusted completion job publishes the download comment. |
| `install.sh` and `install.ps1` | Latest GitHub release bootstrap assets. |

## Errors

| Error | Trigger |
| --- | --- |
| `ThemeAssetError` | Theme asset validation fails. |
| `TemplateAssetError` | Template asset validation fails. |
| `ProjectJustfileExistsError` | Existing `Justfile` lacks overwrite permission. |
| `ProjectJustfileInvalidPackageError` | Package spec is empty, malformed, or contains a pip option. |
| `ProjectJustfileWriteError` | Project root or atomic `Justfile` replacement fails. |
| `ProjectRecipeError` | Project recipe execution invariant fails. |
| `GlobalCliError` | Global console-script install or uninstall invariant fails. |
| `UpdateCheckError` | Update metadata resolution fails. |
| `UpdateSourceEmpty` | Update source has no published package or release. |
| `UpdateInstallError` | Update installation command fails. |
| `JustdocsLinkerError` | MkDocs documentation page has no source path. |

## Browser Errors

| Message | Trigger |
| --- | --- |
| `preferences controls missing` | Preference panel controls are absent. |
| `invalid preference <name>: <value>` | Preference value is not allowed. |
| `search controls missing` | Search controls are absent. |
| `search index fetch failed: <status>` | Search index fetch response is not OK. |
| `search index malformed: docs missing` | Search index JSON has no `docs` array. |
| `mermaid asset missing` | Mermaid global is absent. |
| `theme toggle missing` | Theme toggle controls are absent. |
| `highlight assets missing` | Highlight.js global is absent. |
| `copy button asset missing` | Copy button plugin global is absent. |

## Complexity

| Operation | Time | Space |
| --- | --- | --- |
| Theme asset validation | O(n) | O(n) |
| Template render | O(n + k) | O(n) |
| Search scoring | O(p * q) | O(p) |
| Smart link pass | O(p * t * s) | O(p + t + r) |

`n` is asset or template count, `k` is replacement count, `p` is page or record
count, `q` is query length, `t` is target count, `s` is search cost, and `r` is
protected range count.
