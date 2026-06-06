# Theme Configuration

Theme Configuration controls the visible Justdocs layout through
`extra.justdocs` in `mkdocs.yml`.

## Core Keys

| Key | Values | Contract |
| --- | --- | --- |
| `title` | string | Topbar brand text and document title fallback. |
| `favicon` | string | Inline SVG favicon glyph. |
| `palette.light` | color token map | Light mode CSS token overrides. |
| `palette.dark` | color token map | Dark mode CSS token overrides. |
| `typography.text_font` | CSS font stack | Body and control font family. |
| `typography.mono_font` | CSS font stack | Code and keyboard hint font family. |
| `typography.base_size` | integer pixels | Base content font size. |
| `typography.line_height` | number | Body line-height token. |
| `shape.code_radius` | CSS length | Inline code and focus radius. |
| `shape.control_radius` | CSS length | Button and navigation item radius. |
| `shape.panel_radius` | CSS length | Search, preference, and table card radius. |

## Layout Keys

| Key | Values | Contract |
| --- | --- | --- |
| `layout.content_width` | `narrow`, `standard`, `wide`, `fluid` | Main content max-width token. |
| `layout.density` | `comfortable`, `compact` | Main and nav padding density. |
| `layout.motion` | `system`, `reduced` | Smooth scroll and animation policy. |
| `layout.breakpoints.right_drawer` | integer pixels | Right TOC drawer threshold. |
| `layout.breakpoints.compact_topbar` | integer pixels | Topbar wrapping threshold. |
| `layout.breakpoints.mobile` | integer pixels | Mobile document layout threshold. |
| `layout.breakpoints.small` | integer pixels | Page label hiding threshold. |

## Sidebar Keys

| Key | Left default | Right default | Contract |
| --- | --- | --- | --- |
| `default_width` | `296` | `260` | Initial sidebar width in pixels. |
| `min_width` | `220` | `200` | Pointer and keyboard minimum. |
| `max_width` | `520` | `420` | Width ceiling before viewport clamp. |
| `viewport_ratio` | `0.38` | `0.34` | Maximum share of viewport width. |
| `collapse_margin` | `56` | `56` | Drag hysteresis margin around minimum width. |

## Feature Keys

| Key | Default | Contract |
| --- | --- | --- |
| `preferences.enabled` | `true` | Runtime density, width, and motion panel. |
| `features.preferences` | `true` | Template-level preference panel gate. |
| `features.code_copy` | `true` | Highlight.js copy button controls. |
| `features.mermaid` | `true` | Mermaid block rendering. |
| `features.navigation_scroll` | `true` | Left navigation scroll persistence. |
| `features.search` | `true` | Client-side search UI. |
| `features.sidebars` | `true` | Sidebar toggles, resizing, and drawer behavior. |
| `features.table_labels` | `true` | Header-derived mobile table labels. |
| `features.theme_toggle` | `true` | Light and dark theme toggle. |

## Search Keys

| Key | Default | Contract |
| --- | --- | --- |
| `search.min_chars` | `2` | Minimum query length before searching. |
| `search.limit` | `8` | Maximum rendered result count. |

## Storage Keys

| Key | Storage | Contract |
| --- | --- | --- |
| `justdocs-theme` | `localStorage` | `light` or `dark`. |
| `justdocs-density` | `localStorage` | `comfortable` or `compact`. |
| `justdocs-content-width` | `localStorage` | `narrow`, `standard`, `wide`, or `fluid`. |
| `justdocs-motion` | `localStorage` | `system` or `reduced`. |
| `justdocs-sidebar-left-state` | `localStorage` | Left sidebar collapse state. |
| `justdocs-sidebar-left-width` | `localStorage` | Left sidebar width in pixels. |
| `justdocs-sidebar-right-state` | `localStorage` | Right sidebar collapse state. |
| `justdocs-sidebar-right-width` | `localStorage` | Right sidebar width in pixels. |
| `justdocs-nav-scroll:<site-root>` | `sessionStorage` | Left navigation scroll position. |
