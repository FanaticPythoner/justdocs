# justdocs

Reusable MkDocs theme with local navigation, page sections, dark mode, search, tables, code copy controls, Mermaid, and deterministic smart links.

| Capability | Surface |
| --- | --- |
| Template | `base.html` |
| Styling | `assets/css/theme.css` |
| Behavior | `assets/js/theme.js` |
| Concept | Service Discovery |
| Guide | Deployment Guide |
| Advanced | Traffic Policy |

Service Discovery resolves a stable backend endpoint. Deployment Guide consumes that endpoint. Traffic Policy changes request routing after deployment.

```mermaid
flowchart LR
    A[Service Discovery] --> B[Deployment Guide]
    B --> C[Traffic Policy]
```

```python
from justdocs.paths import theme_dir

print(theme_dir())
```
