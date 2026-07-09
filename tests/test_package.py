from __future__ import annotations

import os
import subprocess
import sys
import unittest
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from justdocs import cli, global_cli, project_recipes, self_update
from justdocs.global_cli import GlobalCliError
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
from justdocs.project_recipes import ProjectRecipeConfig, ProjectRecipeError


class StaticJsonClient:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def read_json(self, url: str, timeout: float) -> dict[str, object]:
        self.urls.append(url)
        return self.payloads[url]


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

    def test_source_justfile_exposes_global_cli_recipes(self) -> None:
        justfile = Path("Justfile").read_text(encoding="utf-8")
        required_terms = (
            'global_python := env_var_or_default("JUSTDOCS_GLOBAL_PYTHON", python)',
            "global-install:",
            "install-global: global-install",
            "global-uninstall:",
            "uninstall-global: global-uninstall",
            "from justdocs.global_cli import main",
            "main(['install', '--project-root', '.'])",
            "main(['uninstall'])",
        )
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, justfile)

    def test_cli_project_init_alias_writes_project_justfile(self) -> None:
        with TemporaryDirectory() as directory:
            exit_code = cli.main(
                [
                    "projects",
                    "init",
                    "--root",
                    directory,
                    "--mkdocs-config",
                    "docs.yml",
                    "--addr",
                    "127.0.0.1:9001",
                    "--package",
                    "justdocs==0.1.0",
                ],
            )
            path = Path(directory) / "Justfile"
            self.assertEqual(0, exit_code)
            self.assertIn('config := env_var_or_default("JUSTDOCS_CONFIG", "docs.yml")', path.read_text(encoding="utf-8"))

    def test_cli_without_args_prints_command_hub(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli.main([])
        rendered = output.getvalue()
        self.assertEqual(0, exit_code)
        self.assertIn("Common commands:", rendered)
        self.assertIn("justdocs project init --root docs-project", rendered)
        self.assertIn("justdocs self check-update", rendered)
        self.assertIn("justdocs self update", rendered)

    def test_cli_project_recipe_dispatches_config(self) -> None:
        with patch.object(project_recipes, "check") as check:
            exit_code = cli.main(
                [
                    "project",
                    "check",
                    "--root",
                    "docs-project",
                    "--mkdocs-config",
                    "docs.yml",
                    "--addr",
                    "127.0.0.1:9001",
                    "--port",
                    "9002",
                    "--package",
                    "justdocs==0.1.0",
                    "--extra-packages",
                    "pymdown-extensions==10.12",
                    "--venv",
                    ".docs-venv",
                    "--python",
                    "python",
                ],
            )
        self.assertEqual(0, exit_code)
        (config,) = check.call_args.args
        self.assertEqual(Path("docs-project"), config.root)
        self.assertEqual("docs.yml", config.mkdocs_config)
        self.assertEqual("127.0.0.1:9001", config.addr)
        self.assertEqual("9002", config.port)
        self.assertEqual("justdocs==0.1.0", config.package)
        self.assertEqual("pymdown-extensions==10.12", config.extra_packages)
        self.assertEqual(Path(".docs-venv"), config.venv)
        self.assertEqual("python", config.python)

    def test_self_update_selects_newest_metadata_candidate(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(repository="FanaticPythoner/justdocs")
        client = StaticJsonClient(
            {
                self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}},
                github_url: {
                    "tag_name": "v0.3.0",
                    "html_url": "https://github.com/FanaticPythoner/justdocs/releases/tag/v0.3.0",
                },
            },
        )
        with (
            patch.object(self_update, "installed_version", return_value="0.1.0"),
            patch.object(self_update, "metadata_repository", return_value="FanaticPythoner/justdocs"),
        ):
            result = self_update.check_update(client=client, timeout=1.0)
        self.assertTrue(result.update_available)
        self.assertIsNotNone(result.latest)
        self.assertEqual("github", result.latest.source)
        self.assertEqual("0.3.0", result.latest.version)
        self.assertEqual((), result.errors)
        self.assertEqual([self_update.PYPI_JSON_URL, github_url], client.urls)

    def test_self_update_reports_current_when_candidate_not_newer(self) -> None:
        client = StaticJsonClient({self_update.PYPI_JSON_URL: {"info": {"version": "0.1.0"}}})
        with patch.object(self_update, "installed_version", return_value="0.1.0"):
            result = self_update.check_update(client=client, timeout=1.0, sources=("pypi",))
        self.assertFalse(result.update_available)
        self.assertIsNone(result.latest)

    def test_self_update_uses_pep440_ordering(self) -> None:
        self.assertLess(self_update.compare_versions("1.0.0rc1", "1.0.0"), 0)
        self.assertGreater(self_update.compare_versions("1.0.0.post1", "1.0.0"), 0)
        self.assertEqual(0, self_update.compare_versions("v1.0.0", "1.0.0"))

    def test_self_update_builds_pypi_install_command(self) -> None:
        with patch.object(self_update, "run_command") as run_command:
            self_update.update_package(version="0.2.0", source="pypi", user=True)
        command = run_command.call_args.args[0]
        self.assertEqual((sys.executable, "-m", "pip", "install", "--upgrade", "--user", "justdocs==0.2.0"), command)

    def test_self_update_builds_github_install_command(self) -> None:
        with (
            patch.object(self_update, "metadata_repository", return_value="FanaticPythoner/justdocs"),
            patch.object(self_update, "run_command") as run_command,
        ):
            self_update.update_package(version="0.2.0", source="github")
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "justdocs @ git+https://github.com/FanaticPythoner/justdocs.git@v0.2.0",
            ),
            command,
        )

    def test_cli_self_update_dispatches_update_command(self) -> None:
        output = StringIO()
        with patch.object(self_update, "update_package") as update_package, redirect_stdout(output):
            exit_code = cli.main(["self", "update", "--source", "github", "--version", "0.2.0", "--user"])
        self.assertEqual(0, exit_code)
        update_package.assert_called_once_with(
            version="0.2.0",
            source="github",
            user=True,
            timeout=self_update.DEFAULT_TIMEOUT_SECONDS,
        )
        self.assertIn("updated justdocs", output.getvalue())

    def test_release_pipeline_uses_dist_action_pypi_publish_and_release_assets(self) -> None:
        release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
        latest = Path(".github/workflows/latest.yml").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        build_action = Path(".github/actions/build-dist/action.yml").read_text(encoding="utf-8")
        release_action = Path(".github/actions/release-assets/action.yml").read_text(encoding="utf-8")
        build_script = Path("scripts/release/build-python-package.sh").read_text(encoding="utf-8")
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", release)
        self.assertIn("PYPI_API_TOKEN", release)
        self.assertIn("artifacts/pypi", release)
        self.assertIn("id-token: write", release)
        self.assertIn("verify-pypi", release)
        self.assertIn("python-version: '3.14'", ci)
        self.assertIn("python-version: '3.14t'", ci)
        self.assertIn("python-version: '3.13t'", ci)
        self.assertIn("os: macos-15", ci)
        self.assertIn("os: windows-2025", ci)
        self.assertIn("actions/setup-python@v6", ci)
        self.assertIn("uses: ./.github/actions/build-dist", ci)
        self.assertIn("uses: ./.github/workflows/reusable-build-python-package.yml", release)
        self.assertIn("uses: ./.github/actions/release-assets", release)
        self.assertIn("uses: ./.github/actions/release-assets", latest)
        self.assertIn("scripts/release/build-python-package.sh", build_action)
        self.assertIn("SHA256SUMS.txt", build_script)
        self.assertIn("cp dist/* install.sh install.ps1 artifacts/release/", build_script)
        self.assertIn("gh release upload", release_action)
        self.assertIn("release create", release_action)
        self.assertIn("packaging>=24,<26", pyproject)
        self.assertIn('license = "GPL-3.0-only"', pyproject)
        self.assertIn('license-files = ["LICENSE"]', pyproject)
        self.assertIn("Programming Language :: Python :: 3.14", pyproject)
        self.assertIn("Programming Language :: Python :: Free Threading :: 2 - Beta", pyproject)

    def test_bootstrap_installers_expose_global_install_contract(self) -> None:
        shell = Path("install.sh").read_text(encoding="utf-8")
        powershell = Path("install.ps1").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        project_setup = Path("examples/basic/docs/guides/project-setup.md").read_text(encoding="utf-8")
        reference = Path("examples/basic/docs/reference.md").read_text(encoding="utf-8")
        docs = "\n".join((readme, project_setup, reference))
        for term in (
            "set -eu",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "python -m pip install --user --upgrade",
            "archive/${ref}.tar.gz",
            "command -v justdocs",
        ):
            with self.subTest(shell_term=term):
                self.assertIn(term, shell)
        for term in (
            "$ErrorActionPreference = 'Stop'",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "-m', 'pip', 'install', '--user', '--upgrade'",
            "archive/$Ref.tar.gz",
            "Get-Command justdocs",
        ):
            with self.subTest(powershell_term=term):
                self.assertIn(term, powershell)
        for term in (
            "curl -fsSL https://raw.githubusercontent.com/FanaticPythoner/justdocs/main/install.sh | sh",
            "irm https://raw.githubusercontent.com/FanaticPythoner/justdocs/main/install.ps1 | iex",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
        ):
            with self.subTest(docs_term=term):
                self.assertIn(term, docs)

        syntax = subprocess.run(("sh", "-n", "install.sh"), check=False, text=True, capture_output=True)
        self.assertEqual("", syntax.stderr)
        self.assertEqual(0, syntax.returncode)

        env = os.environ.copy()
        env.update({"JUSTDOCS_INSTALL_DRY_RUN": "1", "JUSTDOCS_PYTHON": sys.executable})
        dry_run = subprocess.run(("sh", "install.sh"), check=False, env=env, text=True, capture_output=True)
        self.assertEqual("", dry_run.stderr)
        self.assertEqual(0, dry_run.returncode)
        self.assertIn(
            f"{sys.executable} -m pip install --user --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/main.tar.gz",
            dry_run.stdout,
        )

        pypi_env = env | {"JUSTDOCS_INSTALL_SOURCE": "pypi"}
        pypi_run = subprocess.run(("sh", "install.sh"), check=False, env=pypi_env, text=True, capture_output=True)
        self.assertEqual("", pypi_run.stderr)
        self.assertEqual(0, pypi_run.returncode)
        self.assertIn(f"{sys.executable} -m pip install --user --upgrade justdocs", pypi_run.stdout)

        github_env = env | {"JUSTDOCS_INSTALL_SOURCE": "github", "JUSTDOCS_INSTALL_REF": "v0.1.0"}
        github_run = subprocess.run(("sh", "install.sh"), check=False, env=github_env, text=True, capture_output=True)
        self.assertEqual("", github_run.stderr)
        self.assertEqual(0, github_run.returncode)
        self.assertIn(
            f"{sys.executable} -m pip install --user --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/v0.1.0.tar.gz",
            github_run.stdout,
        )

    def test_global_cli_candidates_match_platform_script_names(self) -> None:
        scripts_dir = Path("Scripts")
        names = {path.name for path in global_cli.console_script_candidates(scripts_dir)}
        if os.name == "nt":
            self.assertEqual({"justdocs.exe", "justdocs-script.py", "justdocs"}, names)
        else:
            self.assertEqual({"justdocs"}, names)

    def test_global_cli_install_uses_locked_user_pip(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname = \"justdocs\"\n", encoding="utf-8")
            resolved = root / "bin" / "justdocs"
            with (
                patch.object(global_cli, "install_lock", return_value=nullcontext()),
                patch.object(global_cli, "run_pip") as run_pip,
                patch.object(global_cli, "verify_installed", return_value=resolved) as verify_installed,
            ):
                self.assertEqual(resolved, global_cli.install(root))
        run_pip.assert_called_once_with(("install", "--user", "--upgrade", str(root.resolve())))
        verify_installed.assert_called_once_with()

    def test_global_cli_uninstall_uses_pip_and_verifies(self) -> None:
        with (
            patch.object(global_cli, "run_pip") as run_pip,
            patch.object(global_cli, "verify_uninstalled") as verify_uninstalled,
        ):
            global_cli.uninstall()
        run_pip.assert_called_once_with(("uninstall", "--yes", "justdocs"))
        verify_uninstalled.assert_called_once_with()

    def test_global_cli_install_requires_project_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(GlobalCliError):
                global_cli.install(Path(directory))

    def test_project_recipe_install_runs_venv_and_locked_pip(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            source = Path(directory) / "source"
            root.mkdir()
            source.mkdir()
            (source / "pyproject.toml").write_text("[project]\nname = \"justdocs\"\n", encoding="utf-8")
            config = ProjectRecipeConfig(
                root=root,
                package="../source",
                extra_packages="pymdown-extensions==10.12",
                python="python",
            )
            venv_python = str(config.venv_python)
            with (
                patch.object(project_recipes, "install_lock", return_value=nullcontext()),
                patch.object(project_recipes, "run_command") as run_command,
            ):
                project_recipes.install(config)
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(("python", "-m", "venv", str(config.resolved_venv)), commands[0])
        self.assertEqual((venv_python, "-m", "pip", "install", "--upgrade", "pip"), commands[1])
        self.assertEqual(
            (
                venv_python,
                "-m",
                "pip",
                "install",
                "../source",
                "pymdown-extensions==10.12",
            ),
            commands[2],
        )

    def test_project_recipe_check_runs_strict_mkdocs_build(self) -> None:
        config = ProjectRecipeConfig(root=Path("."), mkdocs_config="docs.yml")
        with (
            patch.object(project_recipes, "install") as install,
            patch.object(project_recipes, "run_command") as run_command,
        ):
            project_recipes.check(config)
        install.assert_called_once_with(config)
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                str(config.venv_python),
                "-m",
                "mkdocs",
                "build",
                "-f",
                "docs.yml",
                "--strict",
                "--clean",
            ),
            command,
        )

    def test_project_recipe_clean_removes_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("site", ".cache", ".mkdocs_cache"):
                path = root / relative
                path.mkdir()
                (path / "file").write_text("x", encoding="utf-8")
            project_recipes.clean(ProjectRecipeConfig(root=root))
            for relative in ("site", ".cache", ".mkdocs_cache"):
                self.assertFalse((root / relative).exists())

    def test_project_recipe_free_port_rejects_invalid_port(self) -> None:
        with self.assertRaises(ProjectRecipeError):
            project_recipes.free_port(ProjectRecipeConfig(port="70000"))

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
        self.assertIn("nav:", config)
        self.assertIn("concepts/theme-configuration.md", config)
        self.assertIn("guides/project-setup.md", config)
        self.assertIn("guides/advanced/smart-links.md", config)
        self.assertIn("palette:", config)
        self.assertIn("typography:", config)
        self.assertIn("shape:", config)
        self.assertIn("features:", config)
        self.assertIn("content_width: standard", config)

    def test_docs_cover_current_contracts(self) -> None:
        root = Path("examples/basic/docs")
        docs = {
            "index": root / "index.md",
            "theme": root / "concepts/theme-configuration.md",
            "setup": root / "guides/project-setup.md",
            "links": root / "guides/advanced/smart-links.md",
            "reference": root / "reference.md",
        }
        for path in docs.values():
            self.assertTrue(path.is_file(), path)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in docs.values())
        readme = Path("README.md").read_text(encoding="utf-8")
        required_terms = (
            "justdocs-linker",
            "min_phrase_chars",
            "max_links_per_page",
            "max_links_per_target",
            "justdocs theme-dir",
            "justdocs project init",
            "justdocs project check",
            "justdocs version --check",
            "justdocs self check-update",
            "justdocs self update",
            "just global-install",
            "just dist",
            "JUSTDOCS_GLOBAL_PYTHON",
            "GlobalCliError",
            "ProjectRecipeError",
            "UpdateCheckError",
            "UpdateInstallError",
            "install.sh",
            "install.ps1",
            "curl -fsSL",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
            "global install failed",
            ".github/actions/build-dist/action.yml",
            ".github/actions/release-assets/action.yml",
            "pypa/gh-action-pypi-publish",
            "PYPI_API_TOKEN",
            "SHA256SUMS.txt",
            "3.14t",
            "packaging>=24,<26",
            "ThemeAssetError",
            "TemplateAssetError",
            "ProjectJustfileExistsError",
            "ProjectJustfileInvalidPackageError",
            "search index fetch failed",
            "copy button asset missing",
            "assets/js/mermaid.LICENSE.txt",
            "justdocs-sidebar-left-state",
            "O(p * t * s)",
        )
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, readme)
                self.assertIn(term, combined)
        stale_terms = (
            "Service " "Discovery",
            "Deployment " "Guide",
            "Traffic " "Policy",
        )
        for term in stale_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, combined)

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
            "| Theme Configuration | [Smart Links](custom.md) |\n\n"
            "Project Setup consumes `Theme Configuration`.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    Theme Configuration --> Project Setup\n"
            "```\n"
            "\n"
            "Theme Configuration remains plain text after the diagram.\n"
        )
        targets = (
            LinkTarget(
                "Theme Configuration",
                "concepts/theme-configuration.md",
                "concepts/theme-configuration.md",
            ),
            LinkTarget("Project Setup", "guides/project-setup.md", "guides/project-setup.md"),
            LinkTarget(
                "Smart Links",
                "guides/advanced/smart-links.md",
                "guides/advanced/smart-links.md",
            ),
        )
        linked = _smart_link_markdown(markdown, "index.md", "index.md", targets, 8)
        self.assertIn("| [Theme Configuration](concepts/theme-configuration.md) |", linked)
        self.assertIn("[Project Setup](guides/project-setup.md) consumes", linked)
        self.assertIn("[Theme Configuration](concepts/theme-configuration.md) remains", linked)
        self.assertIn("`Theme Configuration`", linked)
        self.assertIn("[Smart Links](custom.md)", linked)
        self.assertIn("Theme Configuration --> Project Setup", linked)

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
