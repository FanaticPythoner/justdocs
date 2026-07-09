# Reference

## Package

| Surface | Value |
| --- | --- |
| Name | `justdocs` |
| Version | `0.1.0` |
| Python | `>=3.10` |
| Dependency | `mkdocs>=1.6,<3`, `packaging>=24,<26` |
| Console script | `justdocs = justdocs.cli:main` |
| Theme entry point | `justdocs = justdocs.theme` |
| Plugin entry point | `justdocs-linker = justdocs.plugins:JustdocsLinkerPlugin` |

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

Installers run `python -m pip install --user --upgrade`, then validate that
`justdocs` resolves from the selected interpreter's user script directory.

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
| `ProjectJustfileConfig` | Store root, MkDocs config path, bind address, package spec, and derived port. |
| `render_project_justfile()` | Render the packaged project recipe template. |
| `write_project_justfile()` | Create the project root and write `Justfile`. |
| `ProjectRecipeConfig` | Store project recipe execution inputs. |
| `ProjectRecipeError` | Report project recipe execution invariant failure. |
| `GlobalCliError` | Report global console-script install or uninstall invariant failure. |
| `UpdateCheckError` | Report update metadata resolution failure. |
| `UpdateInstallError` | Report update installation failure. |
| `JustdocsLinkerPlugin` | Insert deterministic cross-page links before Markdown rendering. |

## CLI

| Command | Contract |
| --- | --- |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs init` | Write a project-local `Justfile` from the packaged template. |
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
| `justdocs version --check` | Print current version and newest available PyPI or GitHub release version. |
| `justdocs self check-update` | Query PyPI JSON and GitHub Releases metadata for newer versions. |
| `justdocs self update` | Upgrade the installed package from PyPI or a GitHub release tag. |

## Release Pipeline

| Surface | Contract |
| --- | --- |
| `.github/actions/build-dist/action.yml` | Build sdist, wheel, Twine check, and `SHA256SUMS.txt`. |
| `.github/actions/release-assets/action.yml` | Create GitHub releases and upload distribution assets. |
| `.github/workflows/release.yml` | Publish to PyPI through `pypa/gh-action-pypi-publish` when `PYPI_API_TOKEN` is present. |
| `.github/workflows/latest.yml` | Maintain a moving `latest` prerelease from `main`. |
| `install.sh` and `install.ps1` | GitHub release assets plus raw-repository bootstrap installers. |

## Errors

| Error | Trigger |
| --- | --- |
| `ThemeAssetError` | Theme asset validation fails. |
| `TemplateAssetError` | Template asset validation fails. |
| `ProjectJustfileExistsError` | Existing `Justfile` lacks overwrite permission. |
| `ProjectJustfileInvalidPackageError` | Package spec is empty, malformed, or editable. |
| `ProjectRecipeError` | Project recipe execution invariant fails. |
| `GlobalCliError` | Global console-script install or uninstall invariant fails. |
| `UpdateCheckError` | Update metadata resolution fails. |
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
