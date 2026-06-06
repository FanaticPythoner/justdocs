# Smart Links

Smart Links are inserted by the `justdocs-linker` plugin before Markdown
rendering.

## Plugin Config

```yaml
plugins:
  - search
  - justdocs-linker:
      enabled: true
      min_phrase_chars: 4
      max_links_per_page: 512
      max_links_per_target: 2
```

| Key | Default | Contract |
| --- | --- | --- |
| `enabled` | `true` | Disabled mode stores no targets and returns Markdown unchanged. |
| `min_phrase_chars` | `4` | Shorter normalized phrases are excluded. |
| `max_links_per_page` | `512` | Per-page insertion ceiling. |
| `max_links_per_target` | `2` | Per-target insertion ceiling on one page. |

## Target Generation

| Source | Contract |
| --- | --- |
| Page H1 | Links to the page URL. |
| ATX headings | Links to page URL plus slugified heading fragment. |
| File stem | Hyphen and underscore normalized title. |
| Action stem | `P1-0001-some-title.md` becomes `P1-0001 - Some Title`. |
| Action ID | `P1-0001` links to the action page. |

## Filtering

| Filter | Contract |
| --- | --- |
| Stop phrases | Common navigation words are excluded. |
| Ambiguous phrases | Same phrase pointing to different URLs is excluded. |
| Current page | A page never links to its own source path. |
| Non-text phrase | Phrases with no alphabetic character are excluded. |
| Case | Matching is case-insensitive. |
| Whitespace | Runs of whitespace in the phrase match runs of whitespace in Markdown. |

## Protected Ranges

| Markdown range | Contract |
| --- | --- |
| Fenced code | Never rewritten. |
| Existing links | Link text and URL remain byte-stable. |
| Reference definitions | Remain byte-stable. |
| HTML tags | Remain byte-stable. |
| ATX headings | Remain byte-stable. |
| Inline code | General phrases remain byte-stable. |
| Inline action IDs | `P\d+-\d{4}` tokens can link outside fenced code and existing links. |

## Relative URLs

| Current page | Target | Output |
| --- | --- | --- |
| `guides/project-setup.md` | `concepts/theme-configuration.md` | `../concepts/theme-configuration.md` |
| `index.md` | `guides/advanced/smart-links.md#plugin-config` | `guides/advanced/smart-links.md#plugin-config` |
| `guides/advanced/smart-links.md` | `reference.md` | `../../reference.md` |

## Complexity

| Operation | Time | Space |
| --- | --- | --- |
| Target collection | O(p + h) | O(t) |
| Target dedupe | O(t log t) | O(t) |
| Protected range merge | O(r log r) | O(r) |
| Link pass | O(p * t * s) | O(p + t + r) |
