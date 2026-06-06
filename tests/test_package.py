from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from justdocs.plugins import LinkTarget, _relative_url, _smart_link_markdown
from justdocs.paths import (
    REQUIRED_TEMPLATE_FILES,
    REQUIRED_THEME_FILES,
    project_justfile_template,
    theme_dir,
)
from justdocs.project import (
    ProjectJustfileConfig,
    ProjectJustfileExistsError,
    ProjectJustfileInvalidPackageError,
    render_project_justfile,
    write_project_justfile,
)


class ThemePackageTest(unittest.TestCase):
    def test_theme_dir_contains_required_assets(self) -> None:
        root = theme_dir()
        missing = [path for path in REQUIRED_THEME_FILES if not (root / path).is_file()]
        self.assertEqual([], missing)

    def test_project_templates_are_packaged(self) -> None:
        root = project_justfile_template().parent
        missing = [path for path in REQUIRED_TEMPLATE_FILES if not (root / path).is_file()]
        self.assertEqual([], missing)

    def test_project_justfile_renders_project_local_recipes(self) -> None:
        rendered = render_project_justfile(
            ProjectJustfileConfig(
                root=Path("examples/basic"),
                mkdocs_config="mkdocs.yml",
                addr="127.0.0.1:8020",
                package="../..",
            ),
        )
        self.assertIn('config := env_var_or_default("JUSTDOCS_CONFIG", "mkdocs.yml")', rendered)
        self.assertIn('addr := env_var_or_default("JUSTDOCS_ADDR", "127.0.0.1:8020")', rendered)
        self.assertIn('port := env_var_or_default("JUSTDOCS_PORT", "8020")', rendered)
        self.assertIn('package := env_var_or_default("JUSTDOCS_PACKAGE", "../..")', rendered)
        self.assertIn("assert-package:", rendered)
        self.assertIn("flock", rendered)
        self.assertIn("flock is required for local source package installs", rendered)
        self.assertIn("justdocs-install-locks", rendered)
        self.assertIn("check: install", rendered)
        self.assertIn("build: check", rendered)
        self.assertIn("serve: install", rendered)
        self.assertIn("serve-clean: install", rendered)
        self.assertIn("free-port:", rendered)
        for token in ("{{ mkdocs_config }}", "{{ addr }}", "{{ port }}", "{{ package }}"):
            self.assertNotIn(token, rendered)

    def test_project_justfile_write_refuses_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(ProjectJustfileExistsError):
                write_project_justfile(ProjectJustfileConfig(root=Path(directory)))
            self.assertEqual("existing\n", path.read_text(encoding="utf-8"))

    def test_project_justfile_write_overwrites_with_force(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.write_text("existing\n", encoding="utf-8")
            written = write_project_justfile(
                ProjectJustfileConfig(root=Path(directory), package="justdocs"),
                force=True,
            )
            self.assertEqual(path, written)
            self.assertIn("package := env_var_or_default", path.read_text(encoding="utf-8"))

    def test_project_justfile_rejects_editable_package_specs(self) -> None:
        for package in ("-e ../..", "--editable ../..", "--editable=../.."):
            with self.subTest(package=package):
                with self.assertRaises(ProjectJustfileInvalidPackageError):
                    render_project_justfile(ProjectJustfileConfig(root=Path("."), package=package))

    def test_theme_extends_mkdocs(self) -> None:
        config = (theme_dir() / "mkdocs_theme.yml").read_text(encoding="utf-8")
        self.assertIn("extends: mkdocs", config)

    def test_base_template_references_bundled_assets(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("window.JUSTDOCS", template)
        self.assertIn("rightDrawer", template)
        self.assertIn("contentWidth", template)
        self.assertIn("--font-text", template)
        self.assertIn("--radius-control", template)
        self.assertIn("justdocs_palette_light.link", template)
        self.assertIn("justdocs_palette_dark.link", template)
        self.assertIn("features: {", template)
        self.assertIn('id="hljs-light"', template)
        self.assertIn('id="hljs-dark"', template)
        for asset in REQUIRED_THEME_FILES:
            if not asset.startswith("assets/") or asset.endswith(".txt"):
                continue
            self.assertIn(asset, template)

    def test_base_template_exposes_sidebar_controls(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn('data-sidebar-toggle="left"', template)
        self.assertIn('data-sidebar-toggle="right"', template)
        self.assertIn('data-sidebar-resizer="left"', template)
        self.assertIn('data-sidebar-resizer="right"', template)
        self.assertIn('data-sidebar-restore="left"', template)
        self.assertIn('data-sidebar-restore="right"', template)
        self.assertIn('data-sidebar-scrim="right"', template)
        self.assertIn('role="separator"', template)

    def test_base_template_exposes_preferences(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("justdocs-preferences-panel", template)
        self.assertIn("justdocs_preferences_enabled", template)
        self.assertIn('data-preference-choice="density"', template)
        self.assertIn('data-preference-choice="contentWidth"', template)
        self.assertIn('data-preference-choice="motion"', template)

    def test_main_template_extends_base(self) -> None:
        template = (theme_dir() / "main.html").read_text(encoding="utf-8")
        self.assertEqual('{% extends "base.html" %}', template.strip())

    def test_copy_button_plugin_exports_browser_global(self) -> None:
        plugin = (theme_dir() / "assets/js/highlightjs-copy.min.js").read_text(
            encoding="utf-8",
        )
        self.assertIn("window.CopyButtonPlugin = CopyButtonPlugin;", plugin)

    def test_theme_script_preserves_left_navigation_scroll(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("initializeNavigationScrollState", script)
        self.assertIn("justdocs-nav-scroll", script)
        self.assertIn("sessionStorage.setItem", script)
        self.assertIn("sessionStorage.getItem", script)

    def test_theme_script_resizes_and_collapses_sidebars(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("initializeSidebars", script)
        self.assertIn("justdocs-sidebar", script)
        self.assertIn("collapseMargin", script)
        self.assertIn("applyPointerSidebarWidth", script)
        self.assertIn("setViewportState", script)
        self.assertIn("syncTopbarHeight", script)
        self.assertIn("syncSidebarVisibility", script)
        self.assertIn("const setSidebarCollapsed = (side, collapsed, persist = true)", script)
        self.assertIn('nextViewport === "drawer"', script)
        self.assertIn("initializePreferences", script)
        self.assertIn("setPointerCapture", script)
        self.assertIn("ArrowRight", script)
        self.assertIn("aria-valuenow", script)
        self.assertIn("aria-hidden", script)

    def test_theme_script_uses_configured_features(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("FEATURES", script)
        self.assertIn("PREFERENCES_ENABLED", script)
        self.assertIn("configuredInteger", script)
        self.assertIn('FEATURES.search', script)
        self.assertIn('FEATURES.mermaid', script)
        self.assertIn('FEATURES.codeCopy', script)
        self.assertIn("copy button asset missing", script)

    def test_theme_script_renders_mermaid_blocks(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("initializeMermaid", script)
        self.assertIn("renderMermaidBlocks", script)
        self.assertIn("window.mermaid.run", script)
        self.assertIn("assets/js/mermaid.min.js", template)

    def test_theme_css_prevents_drawer_table_overflow(self) -> None:
        css = (theme_dir() / "assets/css/theme.css").read_text(encoding="utf-8")
        self.assertIn('html[data-justdocs-viewport="drawer"] table', css)
        self.assertIn("table-layout: fixed", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertNotIn("th:nth-child(2)", css)

    def test_theme_css_marks_linked_code_as_links(self) -> None:
        css = (theme_dir() / "assets/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("main a[href]:not(.headerlink)", css)
        self.assertIn("text-decoration-thickness", css)
        self.assertIn("main a[href] > code", css)
        self.assertIn("border: 1px solid color-mix(in srgb, var(--link)", css)

    def test_theme_css_defines_responsive_sidebar_layout(self) -> None:
        css = (theme_dir() / "assets/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("--left-sidebar-width", css)
        self.assertIn("--right-sidebar-width", css)
        self.assertIn("--content-max-width", css)
        self.assertIn("--font-text", css)
        self.assertIn("--radius-control", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("font-family: var(--font-text)", css)
        self.assertIn("font-family: var(--font-mono)", css)
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn(".sidebar-resizer-left", css)
        self.assertIn(".sidebar-restore-left", css)
        self.assertIn(".sidebar-scrim", css)
        self.assertIn(".preferences-panel", css)
        self.assertIn('html[data-justdocs-viewport="mobile"]', css)
        self.assertIn('html[data-left-sidebar="collapsed"] nav.left', css)
        self.assertIn('html[data-left-sidebar="collapsed"] .sidebar-restore-left', css)

    def test_example_documents_customization_surface(self) -> None:
        config = Path("examples/basic/mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("palette:", config)
        self.assertIn("typography:", config)
        self.assertIn("shape:", config)
        self.assertIn("features:", config)
        self.assertIn("content_width: standard", config)

    def test_relative_url_uses_current_page_directory(self) -> None:
        self.assertEqual(
            "../concepts/service-discovery.md",
            _relative_url("guides/deployment-guide.md", "concepts/service-discovery.md"),
        )
        self.assertEqual(
            "guides/deployment-guide.md#release-flow",
            _relative_url("index.md", "guides/deployment-guide.md#release-flow"),
        )

    def test_smart_link_markdown_links_tables_and_prose(self) -> None:
        markdown = (
            "# Home\n\n"
            "| Topic | Existing |\n"
            "| --- | --- |\n"
            "| Service Discovery | [Traffic Policy](custom.md) |\n\n"
            "Deployment Guide consumes `Service Discovery`.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    Service Discovery --> Deployment Guide\n"
            "```\n"
            "\n"
            "Service Discovery remains plain text after the diagram.\n"
        )
        targets = (
            LinkTarget("Service Discovery", "concepts/service-discovery.md", "concepts/service-discovery.md"),
            LinkTarget("Deployment Guide", "guides/deployment-guide.md", "guides/deployment-guide.md"),
            LinkTarget("Traffic Policy", "guides/advanced/traffic-policy.md", "guides/advanced/traffic-policy.md"),
        )
        linked = _smart_link_markdown(markdown, "index.md", "index.md", targets, 8)
        self.assertIn("| [Service Discovery](concepts/service-discovery.md) |", linked)
        self.assertIn("[Deployment Guide](guides/deployment-guide.md) consumes", linked)
        self.assertIn("[Service Discovery](concepts/service-discovery.md) remains", linked)
        self.assertIn("`Service Discovery`", linked)
        self.assertIn("[Traffic Policy](custom.md)", linked)
        self.assertIn("Service Discovery --> Deployment Guide", linked)

    def test_smart_link_markdown_links_action_ids_inside_inline_code(self) -> None:
        markdown = (
            "# P2-0001 - Define Mermaid source contract document\n\n"
            "## Preconditions\n\n"
            "- `P1-0008` complete\n\n"
            "## Dependencies\n\n"
            "- `P2-0002`\n"
            "- `P8-0020`\n\n"
            "```yaml\n"
            "action: P1-0008\n"
            "```\n"
        )
        targets = (
            LinkTarget("P1-0008", "actions/P1/P1-0008-create-stackgraph-model-tests.md", "actions/P1/P1-0008-create-stackgraph-model-tests.md"),
            LinkTarget("P2-0002", "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md", "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md"),
            LinkTarget("P8-0020", "actions/P8/P8-0020-add-docs-freshness-test.md", "actions/P8/P8-0020-add-docs-freshness-test.md"),
        )
        linked = _smart_link_markdown(
            markdown,
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            targets,
            16,
        )
        self.assertIn("[`P1-0008`](../P1/P1-0008-create-stackgraph-model-tests.md)", linked)
        self.assertIn("[`P2-0002`](P2-0002-create-mermaid-parser-package-boundary.md)", linked)
        self.assertIn("[`P8-0020`](../P8/P8-0020-add-docs-freshness-test.md)", linked)
        self.assertIn("action: P1-0008", linked)


if __name__ == "__main__":
    unittest.main()
