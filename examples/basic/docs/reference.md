# Reference

## Package

| Surface | Value |
| --- | --- |
| Name | `justdocs` |
| Version | `0.1.0` |
| Python | `>=3.10` |
| Dependency | `mkdocs>=1.6,<3` |
| Console script | `justdocs = justdocs.cli:main` |
| Theme entry point | `justdocs = justdocs.theme` |
| Plugin entry point | `justdocs-linker = justdocs.plugins:JustdocsLinkerPlugin` |

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
| `JustdocsLinkerPlugin` | Insert deterministic cross-page links before Markdown rendering. |

## CLI

| Command | Contract |
| --- | --- |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs init` | Write a project-local `Justfile` from the packaged template. |

## Errors

| Error | Trigger |
| --- | --- |
| `ThemeAssetError` | Theme asset validation fails. |
| `TemplateAssetError` | Template asset validation fails. |
| `ProjectJustfileExistsError` | Existing `Justfile` lacks overwrite permission. |
| `ProjectJustfileInvalidPackageError` | Package spec is empty, malformed, or editable. |
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
