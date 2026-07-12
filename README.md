# justdocs

Reusable MkDocs package for a documentation theme, project recipe generator, and
deterministic cross-page linker.

| Surface | Contract |
| --- | --- |
| Package | `justdocs` |
| Python | `>=3.10` |
| Runtime dependency | `mkdocs>=1.6,<3`, `packaging>=24` |
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
justdocs projects init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
justdocs projects install --root docs-project
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
| `JUSTDOCS_MODIFY_PATH` | `1` | Add or remove the managed command directory from shell or user PATH configuration. |
| `JUSTDOCS_SHELL_PROFILE` | Detected POSIX shell profile | Explicit POSIX profile path for the managed PATH block. |
| `JUSTDOCS_INSTALL_DRY_RUN` | `0` | Print resolved filesystem, pip, and PATH actions without mutation. |
| `JUSTDOCS_INSTALL_TIMEOUT` | `10` | Positive finite GitHub release lookup timeout in seconds. |
| `JUSTDOCS_REPOSITORY` | `FanaticPythoner/justdocs` | GitHub repository used by `JUSTDOCS_INSTALL_SOURCE=github`. |

The installers create a dedicated virtualenv, install the latest stable GitHub
release wheel without a repository clone, expose its console script under the
managed `bin` directory, configure PATH idempotently, and execute
`justdocs version` as verification. An explicit `JUSTDOCS_INSTALL_REF` selects
the corresponding branch, tag, or commit archive instead.

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
| `justdocs projects init` | Write a project-local `Justfile` and print its absolute path. |
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

| `justdocs projects init` option | Default | Contract |
| --- | --- | --- |
| `--root` | `.` | Project root receiving `Justfile`; parent directories are created. |
| `--mkdocs-config` | `mkdocs.yml` | Project-local MkDocs config path for generated recipes. |
| `--addr` | `127.0.0.1:8000` | MkDocs serve bind address for generated recipes. |
| `--package` | `justdocs` | Wheel, version, or source path used by generated `just install`. |
| `--extra-packages` | `pymdown-extensions==10.12` | Additional package requirements installed with Justdocs. |
| `--venv` | `.venv` | Project-local virtualenv directory. |
| `--force` | `false` | Existing project `Justfile` overwrite gate. |

| Error class | Trigger |
| --- | --- |
| `ThemeAssetError` | Required theme asset is absent. |
| `TemplateAssetError` | Required project template asset is absent. |
| `ProjectJustfileExistsError` | Target `Justfile` exists and `--force` is absent. |
| `ProjectJustfileInvalidPackageError` | Package spec is empty, invalid for shell splitting, or contains a pip option. |
| `ProjectJustfileWriteError` | Project root or atomic `Justfile` replacement fails. |
| `ProjectRecipeError` | Project recipe execution invariant fails. |
| `GlobalCliError` | Global console-script install or uninstall invariant fails. |
| `UpdateCheckError` | PyPI or GitHub metadata is malformed, unreachable, or unsupported. |
| `UpdateSourceEmpty` | PyPI project or GitHub release endpoint has no published release. |
| `UpdateInstallError` | Package update installation command exits non-zero. |

## Generated Project Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Delegate dependency installation to `justdocs projects install` with stored configuration. |
| `just check` | Run `mkdocs build -f <config> --strict --clean`. |
| `just build` | Delegate to `justdocs projects build`. |
| `just serve` | Run `mkdocs serve -f <config> -a <addr>`. |
| `just serve-clean` | Free the configured port, then serve. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove `site`, `.cache`, and `.mkdocs_cache`. |
| `just dist-clean` | Run `clean`, then remove the configured virtualenv directory. |

| Environment variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | Current CLI interpreter | Python executable used to create the project virtualenv. |
| `JUSTDOCS_CONFIG` | Stored `mkdocs_config` | MkDocs config path. |
| `JUSTDOCS_ADDR` | Stored `addr` | MkDocs serve bind address. |
| `JUSTDOCS_PORT` | Port segment from the effective address | Explicit port for `free-port` and `serve-clean`. |
| `JUSTDOCS_PACKAGE` | Stored `package` | Package spec passed to pip after validation. |
| `JUSTDOCS_EXTRA_PACKAGES` | Stored `extra_packages` | Extra pip packages installed with the theme. |
| `JUSTDOCS_VENV` | Stored `venv` | Virtualenv directory. |

The first generated Justfile line stores a bounded, versioned JSON configuration
record. Generated recipes and direct CLI commands read that record before
delegating behavior to `justdocs projects`. Configured virtualenv paths must be
strict descendants of the project root.

Project setting precedence is explicit CLI option, `JUSTDOCS_*` environment
value, generated Justfile record, then package default. `--root`,
`--mkdocs-config`, `--addr`, `--port`, `--package`, `--extra-packages`,
`--venv`, and `--python` use this contract.

## Source Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Create source `.venv` and install the local package plus `pymdown-extensions==10.12`. |
| `just global-install` | Install the source package into the isolated global command environment. |
| `just global-uninstall` | Remove the isolated global command environment and managed PATH entry. |
| `just theme-dir` | Print the absolute theme package path with `PYTHONPATH=.`. |
| `just example-justfile` | Regenerate `examples/basic/Justfile` through `justdocs projects init`. |
| `just test` | Install the source virtualenv and run package tests through `.venv`. |
| `just dist` | Build sdist, wheel, Twine validation, and `SHA256SUMS.txt` through the release build script. |
| `just next-release --bump patch` | Update `pyproject.toml` and `CHANGELOG.md`, create the release commit, and create an annotated SemVer tag. |
| `just next-release --bump patch --push` | Atomically push the release commit and immutable tag after local review. |
| `just example-build` | Run the generated example project `check` recipe. |
| `just example-serve` | Run the generated example project `serve` recipe. |
| `just check` | Run tests and strict example build. |

| Source environment variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_GLOBAL_PYTHON` | `JUSTDOCS_PYTHON` or platform Python | Python executable used by source global install and uninstall recipes. |

Source global recipes delegate to the same platform bootstrap scripts used by
the no-clone install path. Bootstrap locking serializes mutations per install
root, and uninstall refuses to remove an unowned command.

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
| `.github/workflows/release.yml` | Tag release pipeline with tests, reproducible distributions, trusted PyPI publishing, provenance, GitHub release assets, and public publication checks. |
| `.github/workflows/latest.yml` | Moving `latest` prerelease assets for `main`. |
| `.github/workflows/pr-python-dist-comment.yml` | Publish one trusted PR comment linking the CI-built wheel, source archive, installers, and checksum manifest. |
| `install.sh` and `install.ps1` | Latest GitHub release bootstrap assets. |
| `pypa/gh-action-pypi-publish` | PyPI upload action using trusted publishing or `PYPI_API_TOKEN`. |
| PyPI trusted publisher | Default tokenless publication identity: repository `FanaticPythoner/justdocs`, workflow `release.yml`, environment `release`. |
| `PYPI_API_TOKEN` | Explicit token fallback when trusted publishing is unavailable. |
| `CHANGELOG.md` | Persistent stable-release history generated from the Unreleased section and chronological Git commits. |

### Stable Release

PyPI trusted-publisher identity:

| Field | Value |
| --- | --- |
| PyPI project | `justdocs` |
| Owner | `FanaticPythoner` |
| Repository | `justdocs` |
| Workflow | `release.yml` |
| Environment | `release` |

```bash
just check
just dist
just next-release --bump patch --push
```

`next-release` requires a clean default branch equal to `origin`, updates `pyproject.toml` and
`CHANGELOG.md`, creates `release: vX.Y.Z`, creates an annotated `vX.Y.Z` tag, and atomically
pushes branch plus tag only with `--push`. The tag starts the stable workflow. Registry failure
blocks GitHub Release creation. Successful publication requires exact PyPI wheel/sdist digests,
exact GitHub asset digests, exact release notes, the immutable tag target, provenance attestation,
and stable latest-release binding.

Pull-request CI publishes `justdocs-python-dist` for 90 days after all matrix jobs and checksum
round-trip checks pass. A trusted `workflow_run` job maintains one PR comment with the artifact
digest, expiry, run identity, and isolated-install warning without executing pull-request code
under write permissions.

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
