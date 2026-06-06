# Project Justfile Generation Audit

## File Map

| Path | Role |
| --- | --- |
| `justdocs/templates/project.Justfile` | Packaged project-local recipe template. |
| `justdocs/project.py` | Render and write API for generated project `Justfile` files. |
| `justdocs/paths.py` | Template asset path validation. |
| `justdocs/cli.py` | `justdocs init` command surface. |
| `justdocs/theme/assets/css/theme.css` | Responsive docs layout and table behavior. |
| `pyproject.toml` | Package-data inclusion for template assets. |
| `Justfile` | Source-repo harness delegating example build and serve to project recipe. |
| `examples/basic/Justfile` | Generated example project recipe. |
| `README.md` | Project recipe and generator reference. |
| `tests/test_package.py` | Template packaging, render, overwrite, and recipe contract tests. |

## Flow

| Step | Input | Output | Guard |
| --- | --- | --- | --- |
| Template lookup | `justdocs.paths.project_justfile_template()` | `Path` | `project.Justfile` exists in package data. |
| Render | `ProjectJustfileConfig` | Justfile text | Template placeholders are replaced with config values. |
| Write | Project root, `force` flag | Project `Justfile` | Existing file is preserved unless `force=True`. |
| Source example | `just example-justfile` | `examples/basic/Justfile` | Generated through `justdocs init`. |
| Project build | `examples/basic/Justfile` | `examples/basic/site` | MkDocs strict build succeeds from project root. |
| Source install | Local package path | Installed wheel | Editable flags rejected and local source builds are serialized. |
| Drawer table layout | Narrow desktop/tablet viewport | Wrapped table cells | Table min-content does not expand the page grid. |

## Scope Completion Map

| Requirement | Files | Verification |
| --- | --- | --- |
| Per-project serving recipes | `justdocs/templates/project.Justfile`, `examples/basic/Justfile` | `cd examples/basic && just --list`, `cd examples/basic && just serve`. |
| Generator command | `justdocs/cli.py`, `justdocs/project.py` | `examples/basic/.venv/bin/justdocs init --root .tmp-cli-init --addr 127.0.0.1:8123 --force`. |
| Package-installed template availability | `pyproject.toml`, `justdocs/paths.py` | Installed console script generated `.tmp-cli-init/Justfile`. |
| Source repo delegates to project recipe | `Justfile` | `just check` invokes `just example-build`, which invokes `cd examples/basic && just check`. |
| Non-editable project installs | `justdocs/project.py`, `justdocs/templates/project.Justfile`, `examples/basic/Justfile` | `test_project_justfile_rejects_editable_package_specs`, grep scan for `pip install -e`. |
| Serialized local source builds | `Justfile`, `justdocs/templates/project.Justfile`, generated consumer Justfiles | Concurrent `just check` runs across Justdocs, k8s docs projects, and Methodical QA docs. |
| Responsive table layout | `justdocs/theme/assets/css/theme.css`, `tests/test_package.py` | `test_theme_css_prevents_drawer_table_overflow`, Methodical QA browser audit. |
| Overwrite safety | `justdocs/project.py` | `test_project_justfile_write_refuses_existing_file`. |
| Forced regeneration | `justdocs/project.py` | `test_project_justfile_write_overwrites_with_force`. |
| Documentation reference | `README.md` | Manual file audit and `git diff --check`. |

## Determinism

| Surface | Invariant |
| --- | --- |
| Rendering | O(n + k) time, O(n) space for template length `n` and replacement count `k`. |
| Write path | One file write after all replacement operations complete. |
| Overwrite behavior | Existing project `Justfile` remains byte-stable unless `force=True`. |
| Project recipes | `.venv`, MkDocs config, address, port, package spec, and extra packages are env-overridable. |
| Package install mode | Generated specs and runtime env overrides reject `-e` and `--editable`. |
| Source-path installs | Local source package installs use one `flock` lock per canonical package root. |
| Missing install lock support | Local source package installs fail with an explicit invariant error. |
| Drawer tables | Tablet-width tables use fixed layout and breakable cells. |
