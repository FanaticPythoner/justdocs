# justdocs

Reusable MkDocs theme package. The theme is installed through the MkDocs theme entry point
`justdocs` and renders the justdocs documentation layout.

| Surface | Path |
| --- | --- |
| Theme entry point | `justdocs` |
| Theme config | `justdocs/theme/mkdocs_theme.yml` |
| Base template | `justdocs/theme/base.html` |
| Page template | `justdocs/theme/main.html` |
| Theme CSS | `justdocs/theme/assets/css/theme.css` |
| Theme JS | `justdocs/theme/assets/js/theme.js` |
| Example site | `examples/basic` |

## Configuration

```yaml
theme:
  name: justdocs
  locale: en

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
      search: true
      sidebars: true
      table_labels: true
      theme_toggle: true
    search:
      min_chars: 2
      limit: 8
```

| Config path | Contract |
| --- | --- |
| `extra.justdocs.palette.light` | CSS token overrides for light mode. |
| `extra.justdocs.palette.dark` | CSS token overrides for dark mode. |
| `extra.justdocs.typography` | Text stack, monospace stack, base size, body line height. |
| `extra.justdocs.shape` | Radius tokens for code, controls, and panels. |
| `extra.justdocs.layout.content_width` | `narrow`, `standard`, `wide`, or `fluid`. |
| `extra.justdocs.layout.density` | `comfortable` or `compact`. |
| `extra.justdocs.layout.motion` | `system` or `reduced`. |
| `extra.justdocs.layout.breakpoints` | Pixel thresholds for drawer, topbar, mobile, and small states. |
| `extra.justdocs.layout.sidebars` | Default, min, max, viewport ratio, and collapse margin per rail. |
| `extra.justdocs.preferences.enabled` | Runtime density, width, and motion panel. |
| `extra.justdocs.features` | Runtime feature gates for search, Mermaid, sidebars, code copy, table labels, nav scroll, theme toggle. |
| `extra.justdocs.search` | Client search minimum characters and result count. |

## Commands

### Project Commands

```bash
justdocs init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
```

| Generated recipe | Effect |
| --- | --- |
| `just install` | Create project `.venv` and install `justdocs`. |
| `just check` | Strict-build the project MkDocs site. |
| `just build` | Alias for `just check`. |
| `just serve` | Serve the project MkDocs site. |
| `just serve-clean` | Free the configured port, then serve the project MkDocs site. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove project site and MkDocs cache outputs. |
| `just dist-clean` | Remove project outputs and project `.venv`. |

| Generator option | Default | Effect |
| --- | --- | --- |
| `--root` | `.` | Project root receiving `Justfile`. |
| `--mkdocs-config` | `mkdocs.yml` | Project-local MkDocs config path. |
| `--addr` | `127.0.0.1:8000` | Serve bind address. |
| `--package` | `justdocs` | Wheel, version, or source path used by generated `just install`. |
| `--force` | `false` | Overwrite existing project `Justfile`. |

Generated recipes accept env overrides: `JUSTDOCS_PYTHON`, `JUSTDOCS_CONFIG`,
`JUSTDOCS_ADDR`, `JUSTDOCS_PORT`, `JUSTDOCS_PACKAGE`, `JUSTDOCS_EXTRA_PACKAGES`,
`JUSTDOCS_VENV`, `JUSTDOCS_VENV_PYTHON`, and `JUSTDOCS_VENV_MKDOCS`.

### Source Commands

| Command | Effect |
| --- | --- |
| `just install` | Create `.venv` and install the local theme package. |
| `just theme-dir` | Print the absolute theme package path. |
| `just test` | Verify package asset contracts. |
| `just example-build` | Strict-build the bundled example site. |
| `just example-serve` | Serve the bundled example site. |
| `just check` | Run tests and strict example build. |

## Runtime Behavior

| Feature | Contract |
| --- | --- |
| Layout | justdocs topbar, left navigation, content column, right TOC. |
| Theme mode | justdocs light and dark toggle. |
| Search | justdocs search UI backed by MkDocs `search/search_index.json`. |
| Tables | Header labels copied into mobile table cells. |
| Code blocks | Highlight.js plus copy button plugin. |
| Mermaid | Bundled Mermaid asset rendered after page load and after theme changes. |
| Smart links | `justdocs-linker` inserts deterministic cross-page links before Markdown rendering. |
| Sidebars | Pointer, keyboard, collapse, restore, and drawer interactions. |
| Preferences | Local density, width, and motion selections gated by site config. |
