# justdocs

Reusable MkDocs package for a documentation theme, project recipe generator, and
deterministic cross-page linker.

| Surface | Contract |
| --- | --- |
| Package | `justdocs` version `0.1.0` |
| Python | `>=3.10` |
| Runtime dependency | `mkdocs>=1.6,<3`, `packaging>=24,<26` |
| Console script | `justdocs = justdocs.cli:main` |
| Theme entry point | `justdocs = justdocs.theme` |
| Plugin entry point | `justdocs-linker = justdocs.plugins:JustdocsLinkerPlugin` |
| Theme config | `justdocs/theme/mkdocs_theme.yml` |
| Base template | `justdocs/theme/base.html` |
| Page template | `justdocs/theme/main.html` |
| Theme CSS | `justdocs/theme/assets/css/theme.css` |
| Theme JS | `justdocs/theme/assets/js/theme.js` |
| Project recipe template | `justdocs/templates/project.Justfile` |
| Example site | `examples/basic` |

## MkDocs Config

```yaml
site_name: Example Docs

theme:
  name: justdocs
  locale: en

plugins:
  - search
  - justdocs-linker:
      enabled: true
      min_phrase_chars: 4
      max_links_per_page: 512
      max_links_per_target: 2

markdown_extensions:
  - tables
  - pymdownx.highlight:
      pygments_lang_class: true
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - toc:
      permalink: true
      toc_depth: 3

extra:
  justdocs:
    title: Example Docs
    favicon: E
    palette:
      light:
        link: "#075fb8"
      dark:
        link: "#72b7ff"
    typography:
      text_font: Inter, ui-sans-serif, system-ui, sans-serif
      mono_font: '"SFMono-Regular", Consolas, monospace'
      base_size: 16
      line_height: 1.6
    shape:
      code_radius: 0.25rem
      control_radius: 0.45rem
      panel_radius: 0.5rem
    layout:
      content_width: standard
      density: comfortable
      motion: system
      breakpoints:
        right_drawer: 1240
        compact_topbar: 980
        mobile: 860
        small: 520
      sidebars:
        left:
          default_width: 296
          min_width: 220
          max_width: 520
          viewport_ratio: 0.38
          collapse_margin: 56
        right:
          default_width: 260
          min_width: 200
          max_width: 420
          viewport_ratio: 0.34
          collapse_margin: 56
    preferences:
      enabled: true
    features:
      code_copy: true
      mermaid: true
      navigation_scroll: true
      preferences: true
      search: true
      sidebars: true
      table_labels: true
      theme_toggle: true
    search:
      min_chars: 2
      limit: 8
```

| Config path | Default | Contract |
| --- | --- | --- |
| `extra.justdocs.title` | `config.site_name` | Brand text in the topbar and document title. |
| `extra.justdocs.favicon` | `M` | Inline SVG favicon glyph text. |
| `extra.justdocs.palette.light.*` | Built-in light tokens | CSS color token overrides for light mode. |
| `extra.justdocs.palette.dark.*` | Built-in dark tokens | CSS color token overrides for dark mode. |
| `extra.justdocs.typography.text_font` | System sans stack | Body, controls, nav, and panel font stack. |
| `extra.justdocs.typography.mono_font` | System mono stack | Code, kbd, and inline code font stack. |
| `extra.justdocs.typography.base_size` | `16` | Root content font size in pixels. |
| `extra.justdocs.typography.line_height` | `1.6` | Body line-height token. |
| `extra.justdocs.shape.code_radius` | `0.25rem` | Inline code and focus radius token. |
| `extra.justdocs.shape.control_radius` | `0.45rem` | Button, nav item, and control radius token. |
| `extra.justdocs.shape.panel_radius` | `0.5rem` | Panel, table card, and block radius token. |
| `extra.justdocs.layout.content_width` | `standard` | `narrow`, `standard`, `wide`, or `fluid`. |
| `extra.justdocs.layout.density` | `comfortable` | `comfortable` or `compact`. |
| `extra.justdocs.layout.motion` | `system` | `system` or `reduced`. |
| `extra.justdocs.layout.breakpoints.right_drawer` | `1240` | Right TOC switches to drawer at or below this width. |
| `extra.justdocs.layout.breakpoints.compact_topbar` | `980` | Topbar wraps actions at or below this width. |
| `extra.justdocs.layout.breakpoints.mobile` | `860` | Mobile document layout starts at or below this width. |
| `extra.justdocs.layout.breakpoints.small` | `520` | Page label hides at or below this width. |
| `extra.justdocs.layout.sidebars.left.default_width` | `296` | Left sidebar default width in pixels. |
| `extra.justdocs.layout.sidebars.left.min_width` | `220` | Left sidebar keyboard and pointer minimum. |
| `extra.justdocs.layout.sidebars.left.max_width` | `520` | Left sidebar hard maximum before viewport ratio clamp. |
| `extra.justdocs.layout.sidebars.left.viewport_ratio` | `0.38` | Left sidebar viewport-relative maximum. |
| `extra.justdocs.layout.sidebars.left.collapse_margin` | `56` | Pointer collapse hysteresis margin. |
| `extra.justdocs.layout.sidebars.right.default_width` | `260` | Right sidebar default width in pixels. |
| `extra.justdocs.layout.sidebars.right.min_width` | `200` | Right sidebar keyboard and pointer minimum. |
| `extra.justdocs.layout.sidebars.right.max_width` | `420` | Right sidebar hard maximum before viewport ratio clamp. |
| `extra.justdocs.layout.sidebars.right.viewport_ratio` | `0.34` | Right sidebar viewport-relative maximum. |
| `extra.justdocs.layout.sidebars.right.collapse_margin` | `56` | Pointer collapse hysteresis margin. |
| `extra.justdocs.preferences.enabled` | `true` | Runtime density, width, and motion panel. |
| `extra.justdocs.features.preferences` | `true` | Template gate for the preferences panel. |
| `extra.justdocs.search.min_chars` | `2` | Client search query length threshold. |
| `extra.justdocs.search.limit` | `8` | Maximum rendered search results. |

| Feature flag | Default | Runtime contract |
| --- | --- | --- |
| `code_copy` | `true` | Load copy plugin, require `window.CopyButtonPlugin`, and attach copy controls after Highlight.js. |
| `mermaid` | `true` | Render `.mermaid` blocks with bundled Mermaid after load and theme changes. |
| `navigation_scroll` | `true` | Persist left navigation scroll in `sessionStorage`. |
| `search` | `true` | Load `search/search_index.json`, score records, and render client results. |
| `sidebars` | `true` | Enable sidebar toggles, resizers, restore controls, and drawer scrim. |
| `table_labels` | `true` | Copy table header text into mobile cell `data-label` attributes. |
| `theme_toggle` | `true` | Persist light or dark theme in `localStorage`. |

## Browser Behavior

| Surface | Contract |
| --- | --- |
| Viewport | `data-justdocs-viewport` is `desktop`, `drawer`, or `mobile`. |
| Compact topbar | `data-justdocs-compact-topbar` stores the compact breakpoint result. |
| Small viewport | `data-justdocs-small` stores the small breakpoint result. |
| Theme | `data-theme` stores `light` or `dark`; stored key is `justdocs-theme`. |
| Density | `data-justdocs-density`; stored key is `justdocs-density`. |
| Content width | `data-justdocs-content-width`; stored key is `justdocs-content-width`. |
| Motion | `data-justdocs-motion`; stored key is `justdocs-motion`. |
| Left sidebar state | `data-left-sidebar`; stored key is `justdocs-sidebar-left-state`. |
| Left sidebar width | CSS var `--left-sidebar-width`; stored key is `justdocs-sidebar-left-width`. |
| Right sidebar state | `data-right-sidebar`; stored key is `justdocs-sidebar-right-state`. |
| Right sidebar width | CSS var `--right-sidebar-width`; stored key is `justdocs-sidebar-right-width`. |
| Navigation scroll | Session key prefix `justdocs-nav-scroll`. |
| Search index | Fetches `search/search_index.json` relative to `window.JUSTDOCS.baseUrl`. |
| Search ranking | Title prefix +100, title contains +70, URL contains +45, text contains +30, then text offset penalty. |
| Mermaid | Uses `securityLevel: "strict"`, `startOnLoad: false`, and theme `default` or `dark`. |
| Sidebar resizing | Pointer drag, `ArrowLeft`, `ArrowRight`, `Home`, `End`, `Enter`, and Space are supported. |

## Commands

```bash
justdocs theme-dir
justdocs init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs project init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs project install --root docs-project
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
| `justdocs init` | Write a project-local `Justfile` and print its absolute path. |
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

| `justdocs init` option | Default | Contract |
| --- | --- | --- |
| `--root` | `.` | Project root receiving `Justfile`; parent directories are created. |
| `--mkdocs-config` | `mkdocs.yml` | Project-local MkDocs config path for generated recipes. |
| `--addr` | `127.0.0.1:8000` | MkDocs serve bind address for generated recipes. |
| `--package` | `justdocs` | Wheel, version, or source path used by generated `just install`. |
| `--force` | `false` | Existing project `Justfile` overwrite gate. |

| Error class | Trigger |
| --- | --- |
| `ThemeAssetError` | Required theme asset is absent. |
| `TemplateAssetError` | Required project template asset is absent. |
| `ProjectJustfileExistsError` | Target `Justfile` exists and `--force` is absent. |
| `ProjectJustfileInvalidPackageError` | Package spec is empty, invalid for shell splitting, or contains editable install flags. |
| `ProjectRecipeError` | Project recipe execution invariant fails. |
| `GlobalCliError` | Global console-script install or uninstall invariant fails. |
| `UpdateCheckError` | PyPI or GitHub update metadata is absent, malformed, or unreachable. |
| `UpdateInstallError` | Package update installation command exits non-zero. |

## Generated Project Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Create project `.venv`, upgrade pip, install package spec, and install extra packages. |
| `just check` | Run `mkdocs build -f <config> --strict --clean`. |
| `just build` | Alias for `check`. |
| `just serve` | Run `mkdocs serve -f <config> -a <addr>`. |
| `just serve-clean` | Free the configured port, then serve. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove `site`, `.cache`, and `.mkdocs_cache`. |
| `just dist-clean` | Run `clean`, then remove the configured virtualenv directory. |

| Environment variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | `python3` | Python executable used to create the project virtualenv. |
| `JUSTDOCS_CONFIG` | Generator `--mkdocs-config` | MkDocs config path. |
| `JUSTDOCS_ADDR` | Generator `--addr` | MkDocs serve bind address. |
| `JUSTDOCS_PORT` | Port segment from `--addr` | Port passed to `lsof -t -i`. |
| `JUSTDOCS_PACKAGE` | Generator `--package` | Package spec passed to pip after validation. |
| `JUSTDOCS_EXTRA_PACKAGES` | `pymdown-extensions==10.12` | Extra pip packages installed with the theme. |
| `JUSTDOCS_VENV` | `.venv` | Virtualenv directory. |
| `JUSTDOCS_VENV_PYTHON` | `.venv/bin/python` | Virtualenv Python executable. |
| `JUSTDOCS_VENV_MKDOCS` | `.venv/bin/mkdocs` | Virtualenv MkDocs executable. |

Local source package installs are serialized by `flock` with lock files under
`${TMPDIR:-/tmp}/justdocs-install-locks`. Editable installs are rejected by the
generator and by generated recipes.

CLI project recipes use the current Python interpreter by default and mirror
generated project recipe contracts. `--root`, `--mkdocs-config`, `--addr`,
`--port`, `--package`, `--extra-packages`, `--venv`, and `--python` override
the corresponding `JUSTDOCS_*` environment values.

## Source Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Create source `.venv` and install the local package plus `pymdown-extensions==10.12`. |
| `just global-install` | Install the source package into the selected Python user site and verify `justdocs` resolves on `PATH`. |
| `just install-global` | Alias for `global-install`. |
| `just global-uninstall` | Remove `justdocs` from the selected Python environment and verify user-script files are absent. |
| `just uninstall-global` | Alias for `global-uninstall`. |
| `just theme-dir` | Print the absolute theme package path with `PYTHONPATH=.`. |
| `just example-justfile` | Regenerate `examples/basic/Justfile` through `justdocs init`. |
| `just test` | Install the source virtualenv and run package tests through `.venv`. |
| `just dist` | Build sdist, wheel, Twine validation, and `SHA256SUMS.txt` through the release build script. |
| `just example-build` | Run the generated example project `check` recipe. |
| `just example-serve` | Run the generated example project `serve` recipe. |
| `just check` | Run tests and strict example build. |

| Source environment variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_GLOBAL_PYTHON` | `JUSTDOCS_PYTHON` or `python3` | Python executable used by source global install and uninstall recipes. |

Global installs use the current interpreter's user script directory from
`sysconfig`. `global install failed` reports a missing console script, missing
`PATH` entry, or an existing `justdocs` command from a different location.

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

## Smart Links

`justdocs-linker` runs before Markdown rendering.

| Plugin config | Default | Contract |
| --- | --- | --- |
| `enabled` | `true` | Empty target set and identity Markdown transform when false. |
| `min_phrase_chars` | `4` | Minimum normalized phrase length. |
| `max_links_per_page` | `512` | Upper bound for inserted links per page. |
| `max_links_per_target` | `2` | Upper bound for repeated target phrase links per page. |

| Target source | Contract |
| --- | --- |
| Page H1 | Page-level URL. |
| ATX headings `h2` through `h6` | Page URL with `toc.slugify` fragment. |
| File stem | Title-cased stem with hyphen and underscore normalization. |
| Action file stem `P\d+-\d{4}-title` | Action ID plus normalized action title. |
| Action ID | Uppercase `P\d+-\d{4}` URL target. |

| Filter | Contract |
| --- | --- |
| Stop phrases | `about`, `api`, `cli`, `configuration`, `example`, `examples`, `home`, `index`, `introduction`, `overview`, `reference`, `references`, and `summary` are excluded. |
| Ambiguity | A phrase resolving to more than one URL is excluded. |
| Eligibility | Phrase requires `min_phrase_chars` and at least one alphabetic character. |
| Ordering | Longer phrases sort before shorter phrases; ties sort by phrase then URL. |
| Current page | Targets from the current source path are skipped. |

| Protected Markdown range | Contract |
| --- | --- |
| Fenced code | Never linked. |
| Existing inline and reference links | Never rewritten. |
| Reference definitions | Never rewritten. |
| HTML tags | Never rewritten. |
| ATX heading lines | Never rewritten. |
| Inline code | General phrases are not linked inside inline code. |
| Inline action IDs | `P\d+-\d{4}` tokens are linkable inside inline code outside other protected ranges. |

Complexity for one page:

| Operation | Time | Space |
| --- | --- | --- |
| Target collection | O(p + h) | O(t) |
| Target dedupe | O(t log t) | O(t) |
| Protected range merge | O(r log r) | O(r) |
| Smart link pass | O(p * t * s) | O(p + t + r) |

`p` is page Markdown length, `h` is heading count, `t` is eligible target count,
`r` is protected range count, and `s` is regex search cost for a phrase.

## Packaged Assets

| Required asset | Contract |
| --- | --- |
| `theme/404.html` | Static 404 template. |
| `theme/base.html` | Full page layout template. |
| `theme/main.html` | Page template extending `base.html`. |
| `theme/mkdocs_theme.yml` | MkDocs theme metadata. |
| `theme/assets/css/theme.css` | justdocs layout and component CSS. |
| `theme/assets/css/highlightjs.min.css` | Highlight.js GitHub Dark style. |
| `theme/assets/css/highlightjs-copy.min.css` | Copy button style. |
| `theme/assets/js/theme.js` | justdocs runtime. |
| `theme/assets/js/highlightjs.min.js` | Highlight.js v11.9.0 bundle. |
| `theme/assets/js/highlightjs-copy.min.js` | Copy button plugin bundle. |
| `theme/assets/js/mermaid.min.js` | Mermaid bundle. |
| `theme/assets/js/mermaid.LICENSE.txt` | Mermaid MIT license text. |
| `templates/project.Justfile` | Project recipe template. |

## Runtime Errors

| Message | Trigger |
| --- | --- |
| `preferences controls missing` | Preferences feature enabled and required controls absent. |
| `invalid preference <name>: <value>` | Runtime preference value outside the allowed set. |
| `search controls missing` | Search feature enabled and required controls absent. |
| `search index fetch failed: <status>` | Search index response status is not OK. |
| `search index malformed: docs missing` | Search index JSON lacks a `docs` array. |
| `mermaid asset missing` | Mermaid feature enabled and `window.mermaid` absent. |
| `theme toggle missing` | Theme toggle feature enabled and required controls absent. |
| `highlight assets missing` | `window.hljs` absent at code block initialization. |
| `copy button asset missing` | Code copy feature enabled and `window.CopyButtonPlugin` absent. |

## Tests

| Command | Coverage |
| --- | --- |
| `just test` | Asset packaging, templates, project Justfile generation, feature wiring, CSS contracts, docs coverage, update checks, release workflow contracts, and linker behavior. |
