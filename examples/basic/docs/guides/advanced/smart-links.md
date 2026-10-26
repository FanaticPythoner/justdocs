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
| `max_links_per_target` | `2` | Ordinary phrase ceiling; reference IDs retain the page ceiling. |
| `validate_dependencies` | `false` | Validate artifact prerequisites and generate `dependency-graph.json`, independently of link insertion. |
| `dependency_targets` | `[]` | Unique lowercase target names for target-scoped declarations. |

## Target Generation

| Source | Contract |
| --- | --- |
| Page H1 | Links to the page URL. |
| ATX headings | Links to page URL plus slugified heading fragment. |
| File stem | Hyphen and underscore normalized title. |
| Action stem | `P1-0001-some-title.md` becomes `P1-0001 - Some Title`. |
| Action ID | `P1-0001` links to the action page. |
| Heading reference ID | `# [T1] Foundation` declares `T1` for that page; `## [J1] Verify inputs` declares `J1` for that section. |

Heading reference IDs require an alphabetic prefix, trailing digits and optional numeric hyphen segments. Their destinations must be unique across the site. Fenced examples do not declare IDs.

## Artifact Dependencies

Enable `validate_dependencies` to check artifact declarations at every reference heading. Metadata belongs to that heading before the next heading; fenced examples are excluded.

```markdown
## [F7-1] Deliver admission library

**Owner:** Component team
**Requires:** None
**Scope:** shared
**Produces:** Versioned admission library
**Verify:** Pass conformance checks

## [T1] Deliver foundation producer

**Owner:** Infrastructure team
**Requires:** F7-1
**Scope:** shared
**Produces:** Foundation outputs using the admission library
**Verify:** Pass producer-to-library contract tests
```

| Field or check | Contract |
| --- | --- |
| Required fields | Nonempty `Owner`, `Requires`, `Scope`, `Produces` and `Verify`; duplicate metadata fails. |
| Requires | Comma-separated declared IDs or exactly `None`; no prose, negation, unknown or duplicate prerequisites. |
| Scope | `shared`, `build`, `target`; a prerequisite cannot have a later scope than its consumer. |
| Target binding | `dependency_targets: [dev, staging, prod]` expands target nodes separately. A target consumes target-scoped prerequisites from the same target only. |
| Cycles | Every edge is checked, including specifications, models, component delivery and final integration. |
| Report | Generated `dependency-graph.json` records templates, source locations, expanded nodes/edges, topological layers/order and counts. Its source path is reserved while checking is enabled. |
| Evidence boundary | Structural feasibility does not certify implemented artifacts or live execution. |

Parsing takes O(p + h). Graph checking takes O(v log v + e) time and O(v + e) space after target expansion.

## Filtering

| Filter | Contract |
| --- | --- |
| Stop phrases | Common navigation words are excluded. |
| Ambiguous phrases | Same phrase pointing to different URLs is excluded. |
| Current page | Page-self references are skipped; declared section IDs support same-page jumps. |
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
| Inline reference IDs | Declared task/step IDs and action IDs can link outside fenced code and existing links. |

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
