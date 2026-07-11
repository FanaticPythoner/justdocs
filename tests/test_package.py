from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from justdocs import cli, global_cli, project_recipes, self_update
from justdocs.global_cli import GlobalCliError
from justdocs.plugins import (
    JustdocsLinkerError,
    LinkTarget,
    _relative_url,
    _smart_link_markdown,
    _validate_linker_limits,
)
from justdocs.paths import (
    REQUIRED_TEMPLATE_FILES,
    REQUIRED_THEME_FILES,
    project_justfile_template,
    theme_dir,
)
from justdocs.project import (
    ProjectJustfileConfig,
    ProjectJustfileError,
    ProjectJustfileExistsError,
    ProjectJustfileInvalidPackageError,
    ProjectJustfileWriteError,
    PROJECT_CONFIG_PREFIX,
    read_project_justfile_config,
    render_project_justfile,
    split_package_spec,
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


class EmptyJsonClient:
    def read_json(self, url: str, timeout: float) -> dict[str, object]:
        raise self_update.UpdateSourceEmpty(f"no published release at {url}")


def github_release_payload(version: str) -> dict[str, object]:
    """Return GitHub release metadata with one universal wheel."""

    tag = f"v{version}"
    wheel = f"justdocs-{version}-py3-none-any.whl"
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/FanaticPythoner/justdocs/releases/tag/{tag}",
        "assets": [
            {
                "name": wheel,
                "browser_download_url": (
                    f"https://github.com/FanaticPythoner/justdocs/releases/download/{tag}/{wheel}"
                ),
            },
        ],
    }


class ThemePackageTest(unittest.TestCase):
    def test_theme_dir_contains_required_assets(self) -> None:
        root = theme_dir()
        missing = [path for path in REQUIRED_THEME_FILES if not (root / path).is_file()]
        self.assertEqual([], missing)

    def test_project_templates_are_packaged(self) -> None:
        root = project_justfile_template().parent
        missing = [
            path for path in REQUIRED_TEMPLATE_FILES if not (root / path).is_file()
        ]
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
        config_line = rendered.splitlines()[0]
        self.assertTrue(config_line.startswith(PROJECT_CONFIG_PREFIX))
        payload = json.loads(config_line.removeprefix(PROJECT_CONFIG_PREFIX))
        self.assertEqual("mkdocs.yml", payload["mkdocs_config"])
        self.assertEqual("127.0.0.1:8020", payload["addr"])
        self.assertEqual("../..", payload["package"])
        self.assertEqual(1, payload["schema"])
        self.assertIn("justdocs projects install --root .", rendered)
        self.assertIn("justdocs projects check --root .", rendered)
        self.assertIn("justdocs projects build --root .", rendered)
        self.assertIn("justdocs projects serve --root .", rendered)
        self.assertIn("justdocs projects serve-clean --root .", rendered)
        self.assertIn("free-port:", rendered)
        self.assertNotIn("{{ config_json }}", rendered)
        self.assertNotIn("export JUSTDOCS_", rendered)

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
            self.assertTrue(
                path.read_text(encoding="utf-8").startswith(PROJECT_CONFIG_PREFIX)
            )

    @unittest.skipIf(
        os.name == "nt", "Windows symlink privilege is environment-dependent"
    )
    def test_project_justfile_force_replaces_symlink_without_following_it(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.write_text("preserved\n", encoding="utf-8")
            path = root / "Justfile"
            path.symlink_to(outside)
            write_project_justfile(ProjectJustfileConfig(root=root), force=True)
            self.assertFalse(path.is_symlink())
            self.assertEqual("preserved\n", outside.read_text(encoding="utf-8"))

    def test_project_justfile_rejects_directory_target(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.mkdir()
            with self.assertRaises(ProjectJustfileWriteError):
                write_project_justfile(
                    ProjectJustfileConfig(root=Path(directory)), force=True
                )

    def test_project_justfile_rejects_malformed_stored_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            for payload in (
                "{",
                '{"schema":2}',
                '{"addr":1,"extra_packages":"","mkdocs_config":"mkdocs.yml",'
                '"package":"justdocs","schema":1,"venv":".venv"}',
            ):
                with self.subTest(payload=payload):
                    path.write_text(
                        PROJECT_CONFIG_PREFIX + payload + "\n", encoding="utf-8"
                    )
                    with self.assertRaises(ProjectJustfileError):
                        read_project_justfile_config(Path(directory))

    def test_project_justfile_encodes_untrusted_defaults(self) -> None:
        rendered = render_project_justfile(
            ProjectJustfileConfig(
                root=Path("."),
                mkdocs_config='docs "quoted"\nconfig.yml',
                addr="127.0.0.1:8123",
                package='justdocs==0.1.0; printf "unsafe"',
            ),
        )
        self.assertIn('"docs \\"quoted\\"\\nconfig.yml"', rendered)
        self.assertIn('"justdocs==0.1.0; printf \\"unsafe\\""', rendered)
        self.assertNotIn('docs "quoted"\nconfig.yml', rendered)

    def test_project_justfile_rejects_pip_options(self) -> None:
        for package in (
            "-e ../..",
            "--editable ../..",
            "--target /tmp/output justdocs",
        ):
            with self.subTest(package=package):
                with self.assertRaises(ProjectJustfileInvalidPackageError):
                    render_project_justfile(
                        ProjectJustfileConfig(root=Path("."), package=package)
                    )
        with self.assertRaises(ProjectJustfileInvalidPackageError):
            render_project_justfile(
                ProjectJustfileConfig(
                    root=Path("."), extra_packages="--target=/tmp/output"
                ),
            )

    def test_project_justfile_rejects_empty_required_settings(self) -> None:
        for field in ("mkdocs_config", "addr", "venv"):
            with self.subTest(field=field), self.assertRaises(ProjectJustfileError):
                render_project_justfile(
                    ProjectJustfileConfig(root=Path("."), **{field: " "})
                )

    def test_project_package_specs_preserve_single_complex_arguments(self) -> None:
        for package in (
            "../local source",
            r"C:\Program Files\justdocs",
            "justdocs[docs] @ https://example.test/justdocs-1.0.0.tar.gz",
            "justdocs; python_version >= '3.10'",
        ):
            with self.subTest(package=package):
                self.assertEqual((package,), split_package_spec(package))
        self.assertEqual(
            ("first>=1", "second<2"), split_package_spec("first>=1 second<2")
        )

    def test_source_justfile_exposes_global_cli_recipes(self) -> None:
        justfile = Path("Justfile").read_text(encoding="utf-8")
        required_terms = (
            'set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]',
            'global_python := env_var_or_default("JUSTDOCS_GLOBAL_PYTHON", python)',
            "global-install:",
            "global-uninstall:",
            "from justdocs.global_cli import main",
            "main(['install', '--project-root', '.'])",
            "main(['uninstall', '--project-root', '.'])",
            "justdocs.cli projects init",
        )
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, justfile)

    def test_cli_projects_init_writes_project_justfile(self) -> None:
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
            self.assertEqual(0, exit_code)
            stored = read_project_justfile_config(Path(directory))
            self.assertEqual("docs.yml", stored.mkdocs_config)
            self.assertEqual("127.0.0.1:9001", stored.addr)
            self.assertEqual("justdocs==0.1.0", stored.package)

    def test_cli_without_args_prints_command_hub(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli.main([])
        rendered = output.getvalue()
        self.assertEqual(0, exit_code)
        self.assertIn("Common commands:", rendered)
        self.assertIn("justdocs projects init --root docs-project", rendered)
        self.assertIn("justdocs check-update", rendered)
        self.assertIn("justdocs update", rendered)

    def test_cli_rejects_removed_command_aliases(self) -> None:
        for command in (("self", "check-update"), ("project", "check"), ("init",)):
            with (
                self.subTest(command=command),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main(command)
            self.assertEqual(2, raised.exception.code)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(("version", "--check"))
        self.assertEqual(2, raised.exception.code)

    def test_cli_project_recipe_dispatches_config(self) -> None:
        with patch.object(project_recipes, "check") as check:
            exit_code = cli.main(
                [
                    "projects",
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

    def test_cli_project_recipe_loads_generated_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_project_justfile(
                ProjectJustfileConfig(
                    root=root,
                    mkdocs_config="docs.yml",
                    addr="127.0.0.1:9123",
                    package="justdocs==2.0.0",
                    extra_packages="pymdown-extensions==10.12 other-package>=1",
                    venv=".docs-venv",
                ),
            )
            with patch.object(project_recipes, "check") as check:
                exit_code = cli.main(["projects", "check", "--root", str(root)])
        self.assertEqual(0, exit_code)
        (config,) = check.call_args.args
        self.assertEqual("docs.yml", config.mkdocs_config)
        self.assertEqual("127.0.0.1:9123", config.addr)
        self.assertEqual("justdocs==2.0.0", config.package)
        self.assertEqual(
            "pymdown-extensions==10.12 other-package>=1", config.extra_packages
        )
        self.assertEqual(Path(".docs-venv"), config.venv)
        self.assertEqual("9123", config.port_value)

    def test_self_update_selects_newest_metadata_candidate(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        client = StaticJsonClient(
            {
                self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}},
                github_url: github_release_payload("0.3.0"),
            },
        )
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
        ):
            result = self_update.check_update(client=client, timeout=1.0)
        self.assertTrue(result.update_available)
        self.assertIsNotNone(result.latest)
        self.assertEqual("github", result.latest.source)
        self.assertEqual("0.3.0", result.latest.version)
        self.assertEqual((), result.errors)
        self.assertEqual([self_update.PYPI_JSON_URL, github_url], client.urls)

    def test_self_update_reports_current_when_candidate_not_newer(self) -> None:
        client = StaticJsonClient(
            {self_update.PYPI_JSON_URL: {"info": {"version": "0.1.0"}}}
        )
        with patch.object(self_update, "installed_version", return_value="0.1.0"):
            result = self_update.check_update(
                client=client, timeout=1.0, sources=("pypi",)
            )
        self.assertFalse(result.update_available)
        self.assertIsNone(result.latest)

    def test_self_update_reports_unpublished_sources_without_failure(self) -> None:
        with patch.object(self_update, "installed_version", return_value="0.1.0"):
            result = self_update.check_update(client=EmptyJsonClient(), timeout=1.0)
        self.assertFalse(result.update_available)
        self.assertEqual(2, len(result.errors))
        self.assertTrue(
            all(error.startswith("no published release at ") for error in result.errors)
        )

    def test_self_update_fails_when_empty_source_coexists_with_transport_failure(
        self,
    ) -> None:
        class MixedJsonClient:
            def read_json(self, url: str, timeout: float) -> dict[str, object]:
                if url == self_update.PYPI_JSON_URL:
                    raise self_update.UpdateSourceEmpty(
                        f"no published release at {url}"
                    )
                raise self_update.UpdateCheckError(
                    f"update check failed for {url}: unavailable"
                )

        with self.assertRaises(self_update.UpdateCheckError):
            self_update.check_update(client=MixedJsonClient(), timeout=1.0)

    def test_self_update_uses_pep440_ordering(self) -> None:
        self.assertLess(self_update.compare_versions("1.0.0rc1", "1.0.0"), 0)
        self.assertGreater(self_update.compare_versions("1.0.0.post1", "1.0.0"), 0)
        self.assertEqual(0, self_update.compare_versions("v1.0.0", "1.0.0"))

    def test_self_update_accepts_only_canonical_github_repository_urls(self) -> None:
        self.assertEqual(
            "FanaticPythoner/justdocs",
            self_update.repository_slug_from_url(
                "https://github.com/FanaticPythoner/justdocs.git"
            ),
        )
        for url in (
            "http://github.com/FanaticPythoner/justdocs",
            "https://example.test/github.com/FanaticPythoner/justdocs",
            "https://github.com/FanaticPythoner/justdocs/releases",
            "https://github.com/FanaticPythoner/justdocs?ref=main",
            "https://github.com@attacker.test/FanaticPythoner/justdocs",
            "git@github.com:FanaticPythoner/justdocs.git",
        ):
            with self.subTest(url=url):
                self.assertIsNone(self_update.repository_slug_from_url(url))

    def test_self_update_requires_installed_repository_metadata(self) -> None:
        with (
            patch.object(
                self_update.metadata,
                "metadata",
                side_effect=self_update.metadata.PackageNotFoundError,
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.metadata_repository()

    def test_self_update_requires_unique_release_wheel_asset(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        payload = github_release_payload("0.2.0")
        payload["assets"] = []
        client = StaticJsonClient({github_url: payload})
        with (
            patch.object(self_update, "installed_version", return_value="0.1.0"),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.check_update(client=client, timeout=1.0, sources=("github",))

    def test_self_update_rejects_oversized_metadata(self) -> None:
        class OversizedResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit: int) -> bytes:
                return b"x" * limit

        with (
            patch.object(
                self_update.urllib.request, "urlopen", return_value=OversizedResponse()
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.UrlJsonClient().read_json(self_update.PYPI_JSON_URL, 1.0)

    def test_self_update_builds_pypi_install_command(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(self_update, "pip_scope_args", return_value=("--user",)),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(version="0.2.0", source="pypi")
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--user",
                "justdocs==0.2.0",
            ),
            command,
        )
        self.assertTrue(result.changed)
        self.assertEqual("0.2.0", result.target_version)

    def test_self_update_builds_github_install_command(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            patch.object(self_update, "pip_scope_args", return_value=()),
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
                "https://github.com/FanaticPythoner/justdocs/releases/download/"
                "v0.2.0/justdocs-0.2.0-py3-none-any.whl",
            ),
            command,
        )

    def test_cli_update_dispatches_update_command(self) -> None:
        output = StringIO()
        result = self_update.UpdateInstallResult("0.1.0", "0.2.0", "github", True)
        with (
            patch.object(
                self_update, "update_package", return_value=result
            ) as update_package,
            redirect_stdout(output),
        ):
            exit_code = cli.main(["update", "--source", "github", "--version", "0.2.0"])
        self.assertEqual(0, exit_code)
        update_package.assert_called_once_with(
            version="0.2.0",
            source="github",
            timeout=self_update.DEFAULT_TIMEOUT_SECONDS,
        )
        self.assertIn("updated justdocs 0.1.0 -> 0.2.0 from github", output.getvalue())

    def test_cli_update_reports_current_without_claiming_install(self) -> None:
        output = StringIO()
        result = self_update.UpdateInstallResult("0.2.0", "0.2.0", "pypi", False)
        with (
            patch.object(self_update, "update_package", return_value=result),
            redirect_stdout(output),
        ):
            exit_code = cli.main(["update"])
        self.assertEqual(0, exit_code)
        self.assertEqual("justdocs 0.2.0 is current\n", output.getvalue())

    def test_self_update_auto_installs_newest_release_wheel(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        client = StaticJsonClient(
            {
                self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}},
                github_url: github_release_payload("0.3.0"),
            },
        )
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.3.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            patch.object(self_update, "pip_scope_args", return_value=()),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(client=client, timeout=1.0)
        self.assertEqual("github", result.source)
        self.assertIn(
            "releases/download/v0.3.0/justdocs-0.3.0-py3-none-any.whl",
            run_command.call_args.args[0][-1],
        )

    def test_self_update_skips_current_version(self) -> None:
        client = StaticJsonClient(
            {self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}}}
        )
        with (
            patch.object(self_update, "installed_version", return_value="0.2.0"),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(
                source="pypi", client=client, timeout=1.0
            )
        self.assertFalse(result.changed)
        run_command.assert_not_called()

    def test_self_update_rejects_unverified_install_result(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.1.0")
            ),
            patch.object(self_update, "run_command"),
            self.assertRaises(self_update.UpdateInstallError),
        ):
            self_update.update_package(version="0.2.0", source="pypi")

    def test_self_update_rejects_downgrade_and_ambiguous_explicit_source(self) -> None:
        with patch.object(self_update, "installed_version", return_value="0.2.0"):
            with self.assertRaises(self_update.UpdateInstallError):
                self_update.update_package(version="0.1.0", source="pypi")
            with self.assertRaises(self_update.UpdateInstallError):
                self_update.update_package(version="0.3.0", source="auto")

    def test_self_update_rejects_invalid_timeouts_and_empty_sources(self) -> None:
        for timeout in (0.0, -1.0, float("inf"), float("nan")):
            with (
                self.subTest(timeout=timeout),
                self.assertRaises(self_update.UpdateCheckError),
            ):
                self_update.check_update(timeout=timeout)
        with self.assertRaises(self_update.UpdateCheckError):
            self_update.check_update(sources=())

    def test_self_update_selects_pip_scope_from_interpreter(self) -> None:
        with (
            patch.object(sys, "prefix", "/venv"),
            patch.object(sys, "base_prefix", "/base"),
        ):
            self.assertEqual((), self_update.pip_scope_args())
        with TemporaryDirectory() as directory:
            user_site = Path(directory) / "user-site"
            system_site = Path(directory) / "system-site"
            for distribution_root, expected in (
                (user_site, ("--user",)),
                (system_site, ()),
            ):
                with (
                    self.subTest(distribution_root=distribution_root),
                    patch.object(sys, "prefix", "/base"),
                    patch.object(sys, "base_prefix", "/base"),
                    patch.object(
                        self_update.site,
                        "getusersitepackages",
                        return_value=str(user_site),
                    ),
                    patch.object(
                        self_update,
                        "installed_distribution_root",
                        return_value=distribution_root,
                    ),
                ):
                    self.assertEqual(expected, self_update.pip_scope_args())

    def test_self_update_requires_installed_distribution_for_scope(self) -> None:
        with (
            patch.object(
                self_update.metadata,
                "distribution",
                side_effect=self_update.metadata.PackageNotFoundError,
            ),
            self.assertRaises(self_update.UpdateInstallError),
        ):
            self_update.installed_distribution_root()

    def test_cli_check_update_dispatches_top_level_command(self) -> None:
        result = self_update.UpdateCheckResult(current_version="0.1.0", latest=None)
        output = StringIO()
        with (
            patch.object(
                self_update, "check_update", return_value=result
            ) as check_update,
            redirect_stdout(output),
        ):
            exit_code = cli.main(
                ["check-update", "--source", "pypi", "--timeout", "1.5"]
            )
        self.assertEqual(0, exit_code)
        check_update.assert_called_once_with(timeout=1.5, sources=("pypi",))
        self.assertIn("current: 0.1.0", output.getvalue())
        self.assertIn("latest: current", output.getvalue())

    def test_release_pipeline_uses_dist_action_pypi_publish_and_release_assets(
        self,
    ) -> None:
        release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
        latest = Path(".github/workflows/latest.yml").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        build_action = Path(".github/actions/build-dist/action.yml").read_text(
            encoding="utf-8"
        )
        release_action = Path(".github/actions/release-assets/action.yml").read_text(
            encoding="utf-8"
        )
        build_script = Path("scripts/release/build-python-package.sh").read_text(
            encoding="utf-8"
        )
        metadata_script = Path("scripts/release/resolve-release-metadata.sh").read_text(
            encoding="utf-8"
        )
        reusable = Path(
            ".github/workflows/reusable-build-python-package.yml"
        ).read_text(encoding="utf-8")
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", release)
        self.assertIn("PYPI_API_TOKEN", release)
        self.assertIn("PYPI_TRUSTED_PUBLISHING", release)
        self.assertIn("Publish to PyPI with trusted publishing", release)
        self.assertIn("Publish to PyPI with API token", release)
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
        self.assertIn(
            "uses: ./.github/workflows/reusable-build-python-package.yml", release
        )
        self.assertNotIn("secrets: inherit", release)
        self.assertNotIn("secrets: inherit", latest)
        self.assertIn("uses: ./.github/actions/release-assets", release)
        self.assertIn("uses: ./.github/actions/release-assets", latest)
        self.assertIn("scripts/release/build-python-package.sh", build_action)
        self.assertIn("SHA256SUMS.txt", build_script)
        self.assertIn(
            "cp dist/* install.sh install.ps1 artifacts/release/", build_script
        )
        self.assertIn("source scripts/release/release-artifacts.sh", release)
        self.assertIn("version.is_prerelease", metadata_script)
        self.assertNotIn("release_tag:", reusable)
        self.assertIn("gh release upload", release_action)
        self.assertIn("release create", release_action)
        self.assertIn("packaging>=24", pyproject)
        self.assertNotIn("packaging>=24,<", pyproject)
        self.assertIn('requires = ["setuptools==83.0.0"]', pyproject)
        self.assertIn('"build==1.5.1"', pyproject)
        self.assertIn('"twine==6.2.0"', pyproject)
        self.assertIn("SOURCE_DATE_EPOCH", build_script)
        self.assertIn("PYTHONHASHSEED", build_script)
        self.assertIn("gzip.GzipFile", build_script)
        self.assertIn('license = "GPL-3.0-only"', pyproject)
        self.assertIn('license-files = ["LICENSE"]', pyproject)
        self.assertIn("Programming Language :: Python :: 3.14", pyproject)
        self.assertIn(
            "Programming Language :: Python :: Free Threading :: 2 - Beta", pyproject
        )

    def test_release_verification_rejects_invalid_polling_bounds(self) -> None:
        for option in ("--interval-seconds", "--timeout-seconds"):
            with self.subTest(option=option):
                completed = subprocess.run(
                    (
                        sys.executable,
                        "scripts/release/verify-pypi.py",
                        "--package",
                        "justdocs",
                        "--version",
                        "0.1.0",
                        option,
                        "0",
                    ),
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(2, completed.returncode)
                self.assertIn("must be a positive finite number", completed.stderr)

    @unittest.skipIf(os.name == "nt", "Bash release helper path")
    def test_release_versioning_orders_pep440_tags(self) -> None:
        versioning_script = Path("scripts/release/release-versioning.sh").resolve()
        with TemporaryDirectory() as directory:
            fake_git = Path(directory) / "git"
            fake_git.write_text(
                "#!/bin/sh\nprintf '%s\\n' v1.0.0 v1.1.0rc1 invalid v1.0.1 v1.1.0 v1.1.0.post1\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            env = os.environ | {
                "PATH": os.pathsep.join(
                    (directory, str(Path(sys.executable).parent), os.environ["PATH"])
                ),
            }
            completed = subprocess.run(
                (
                    "bash",
                    "-c",
                    'source "$1"; latest_release_tag; previous_release_tag v1.1.0',
                    "bash",
                    str(versioning_script),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(["v1.1.0.post1", "v1.1.0rc1"], completed.stdout.splitlines())

    def test_bootstrap_installers_expose_global_install_contract(self) -> None:
        shell = Path("install.sh").read_text(encoding="utf-8")
        powershell = Path("install.ps1").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        project_setup = Path("examples/basic/docs/guides/project-setup.md").read_text(
            encoding="utf-8"
        )
        reference = Path("examples/basic/docs/reference.md").read_text(encoding="utf-8")
        docs = "\n".join((readme, project_setup, reference))
        for term in (
            "set -eu",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_TIMEOUT",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_MODIFY_PATH",
            "justdocs-managed-v1",
            "-m pip install --upgrade",
            "archive/${ref}.tar.gz",
            "api.github.com/repos/{repository}/releases/latest",
            "browser_download_url",
            "# >>> justdocs PATH >>>",
            '"$command_path" version',
        ):
            with self.subTest(shell_term=term):
                self.assertIn(term, shell)
        for term in (
            "$ErrorActionPreference = 'Stop'",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_TIMEOUT",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_MODIFY_PATH",
            "-m pip install --upgrade",
            "archive/$Ref.tar.gz",
            "api.github.com/repos/{repository}/releases/latest",
            "browser_download_url",
            "SetEnvironmentVariable('Path'",
            "& $CommandPath version",
        ):
            with self.subTest(powershell_term=term):
                self.assertIn(term, powershell)
        for term in (
            "curl -fsSL https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.sh | sh",
            "irm https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.ps1 | iex",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
        ):
            with self.subTest(docs_term=term):
                self.assertIn(term, docs)

        syntax = subprocess.run(
            ("sh", "-n", "install.sh"), check=False, text=True, capture_output=True
        )
        self.assertEqual("", syntax.stderr)
        self.assertEqual(0, syntax.returncode)
        if os.name != "nt":
            self.assertTrue(os.access("install.sh", os.X_OK))

        if os.name == "nt":
            with TemporaryDirectory() as directory:
                root = Path(directory) / "justdocs"
                windows_env = os.environ | {
                    "JUSTDOCS_INSTALL_DRY_RUN": "1",
                    "JUSTDOCS_PYTHON": sys.executable,
                    "JUSTDOCS_INSTALL_ROOT": str(root),
                    "JUSTDOCS_INSTALL_REF": "v0.1.0",
                }
                windows_run = subprocess.run(
                    (
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        "install.ps1",
                    ),
                    check=False,
                    env=windows_env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual("", windows_run.stderr)
                self.assertEqual(0, windows_run.returncode)
                self.assertIn("archive/v0.1.0.tar.gz", windows_run.stdout)
            return

        env = os.environ.copy()
        env.update(
            {
                "JUSTDOCS_INSTALL_DRY_RUN": "1",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_INSTALL_ROOT": "/tmp/justdocs-test-root",
                "JUSTDOCS_SHELL_PROFILE": "/tmp/justdocs-test-profile",
                "JUSTDOCS_INSTALL_REF": "v0.1.0",
            },
        )
        dry_run = subprocess.run(
            ("sh", "install.sh"), check=False, env=env, text=True, capture_output=True
        )
        self.assertEqual("", dry_run.stderr)
        self.assertEqual(0, dry_run.returncode)
        self.assertIn(
            f"{sys.executable} -m venv /tmp/justdocs-test-root/venv", dry_run.stdout
        )
        self.assertIn(
            "/tmp/justdocs-test-root/venv/bin/python -m pip install --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/v0.1.0.tar.gz",
            dry_run.stdout,
        )
        self.assertIn("link /tmp/justdocs-test-root/bin/justdocs", dry_run.stdout)

        with TemporaryDirectory() as resolver_directory:
            payload = json.dumps(github_release_payload("0.1.0"))
            Path(resolver_directory, "sitecustomize.py").write_text(
                "import io\n"
                "import urllib.request\n"
                f"PAYLOAD = {payload!r}.encode('utf-8')\n"
                "class Response(io.BytesIO):\n"
                "    def __enter__(self): return self\n"
                "    def __exit__(self, exc_type, exc_value, traceback): return False\n"
                "urllib.request.urlopen = lambda request, timeout: Response(PAYLOAD)\n",
                encoding="utf-8",
            )
            resolver_env = env | {"PYTHONPATH": resolver_directory}
            resolver_env.pop("JUSTDOCS_INSTALL_REF")
            latest_run = subprocess.run(
                ("sh", "install.sh"),
                check=False,
                env=resolver_env,
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, latest_run.returncode, latest_run.stderr)
        self.assertIn(
            "releases/download/v0.1.0/justdocs-0.1.0-py3-none-any.whl",
            latest_run.stdout,
        )

        invalid_boolean = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=env | {"JUSTDOCS_MODIFY_PATH": "invalid"},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_boolean.returncode)
        self.assertIn("invalid JUSTDOCS_MODIFY_PATH", invalid_boolean.stderr)

        invalid_spec = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=env | {"JUSTDOCS_INSTALL_SPEC": "--target=/tmp/justdocs justdocs"},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_spec.returncode)
        self.assertIn("pip option rejected", invalid_spec.stderr)

        latest_env = env | {"JUSTDOCS_INSTALL_TIMEOUT": "invalid"}
        latest_env.pop("JUSTDOCS_INSTALL_REF")
        invalid_timeout = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=latest_env,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_timeout.returncode)
        self.assertIn("invalid JUSTDOCS_INSTALL_TIMEOUT", invalid_timeout.stderr)

        pypi_env = env | {"JUSTDOCS_INSTALL_SOURCE": "pypi"}
        pypi_run = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=pypi_env,
            text=True,
            capture_output=True,
        )
        self.assertEqual("", pypi_run.stderr)
        self.assertEqual(0, pypi_run.returncode)
        self.assertIn(
            "/tmp/justdocs-test-root/venv/bin/python -m pip install --upgrade justdocs",
            pypi_run.stdout,
        )

        github_env = env | {
            "JUSTDOCS_INSTALL_SOURCE": "github",
            "JUSTDOCS_INSTALL_REF": "v0.1.0",
        }
        github_run = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=github_env,
            text=True,
            capture_output=True,
        )
        self.assertEqual("", github_run.stderr)
        self.assertEqual(0, github_run.returncode)
        self.assertIn(
            "/tmp/justdocs-test-root/venv/bin/python -m pip install --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/v0.1.0.tar.gz",
            github_run.stdout,
        )

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap safety path")
    def test_bootstrap_uninstall_rejects_unsafe_and_unmanaged_roots(self) -> None:
        with TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            profile = home / ".bashrc"
            unmanaged = Path(directory) / "unmanaged"
            home.mkdir()
            unmanaged.mkdir()
            marker = unmanaged / "preserved"
            marker.write_text("x", encoding="utf-8")
            tampered = Path(directory) / "tampered"
            (tampered / "bin").mkdir(parents=True)
            (tampered / ".justdocs-managed").write_text(
                "justdocs-managed-v1\n", encoding="utf-8"
            )
            tampered_command = tampered / "bin" / "justdocs"
            tampered_command.write_text("unowned\n", encoding="utf-8")
            marker_target = Path(directory) / "marker-target"
            marker_target.write_text("justdocs-managed-v1\n", encoding="utf-8")
            linked_marker = Path(directory) / "linked-marker"
            linked_marker.mkdir()
            (linked_marker / ".justdocs-managed").symlink_to(marker_target)
            base_env = os.environ | {
                "HOME": str(home),
                "SHELL": "/bin/bash",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_SHELL_PROFILE": str(profile),
                "JUSTDOCS_INSTALL_ACTION": "uninstall",
            }
            for root, expected in (
                (home, "unsafe JUSTDOCS_INSTALL_ROOT"),
                (unmanaged, "refusing to remove unmanaged install root"),
                (tampered, "refusing to modify unowned command"),
                (linked_marker, "invalid install ownership marker symlink"),
            ):
                with self.subTest(root=root):
                    completed = subprocess.run(
                        ("sh", "install.sh"),
                        env=base_env | {"JUSTDOCS_INSTALL_ROOT": str(root)},
                        check=False,
                        text=True,
                        capture_output=True,
                    )
                    self.assertNotEqual(0, completed.returncode)
                    self.assertIn(expected, completed.stderr)
            self.assertEqual("x", marker.read_text(encoding="utf-8"))
            self.assertEqual("unowned\n", tampered_command.read_text(encoding="utf-8"))
            self.assertEqual(
                "justdocs-managed-v1\n", marker_target.read_text(encoding="utf-8")
            )

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap lock path")
    def test_bootstrap_recovers_stale_lock_and_rejects_live_lock(self) -> None:
        with TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            root = Path(directory) / "managed"
            lock = Path(str(root) + ".install-lock")
            home.mkdir()
            lock.mkdir()
            (lock / "pid").write_text("999999999\n", encoding="utf-8")
            environment = os.environ | {
                "HOME": str(home),
                "SHELL": "/bin/bash",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_INSTALL_ROOT": str(root),
                "JUSTDOCS_SHELL_PROFILE": str(home / ".bashrc"),
                "JUSTDOCS_INSTALL_ACTION": "uninstall",
            }
            recovered = subprocess.run(
                ("sh", "install.sh"),
                env=environment,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, recovered.returncode, recovered.stderr)
            self.assertFalse(lock.exists())

            lock.mkdir()
            (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            held = subprocess.run(
                ("sh", "install.sh"),
                env=environment,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(0, held.returncode)
            self.assertIn("installer lock is held", held.stderr)

    def test_global_cli_install_delegates_to_platform_bootstrap(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "justdocs"\n', encoding="utf-8"
            )
            (root / ("install.ps1" if os.name == "nt" else "install.sh")).write_text(
                "", encoding="utf-8"
            )
            environment = {"JUSTDOCS_INSTALL_ROOT": str(root / "managed")}
            resolved = (
                root
                / "managed"
                / "bin"
                / ("justdocs.exe" if os.name == "nt" else "justdocs")
            )
            with (
                patch.object(
                    global_cli, "bootstrap_environment", return_value=environment
                ) as bootstrap_environment,
                patch.object(global_cli, "run_bootstrap") as run_bootstrap,
            ):
                self.assertEqual(resolved, global_cli.install(root))
        bootstrap_environment.assert_called_once_with("install", root.resolve())
        run_bootstrap.assert_called_once_with(root.resolve(), environment)

    def test_global_cli_uninstall_delegates_to_platform_bootstrap(self) -> None:
        root = Path.cwd().resolve()
        environment = {"JUSTDOCS_INSTALL_ACTION": "uninstall"}
        with (
            patch.object(global_cli, "bootstrap_environment", return_value=environment),
            patch.object(
                global_cli,
                "run_bootstrap",
            ) as run_bootstrap,
        ):
            global_cli.uninstall(root)
        run_bootstrap.assert_called_once_with(root, environment)

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
            (source / "pyproject.toml").write_text(
                '[project]\nname = "justdocs"\n', encoding="utf-8"
            )
            config = ProjectRecipeConfig(
                root=root,
                package="../source",
                extra_packages="pymdown-extensions==10.12",
                python="python",
            )
            venv_python = str(config.venv_python)
            with (
                patch.object(
                    project_recipes, "install_lock", return_value=nullcontext()
                ),
                patch.object(project_recipes, "run_command") as run_command,
            ):
                project_recipes.install(config)
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(
            ("python", "-m", "venv", str(config.resolved_venv)), commands[0]
        )
        self.assertEqual(
            (
                venv_python,
                "-m",
                "pip",
                "install",
                "../source",
                "pymdown-extensions==10.12",
            ),
            commands[1],
        )

    def test_project_recipe_locks_all_local_sources_in_sorted_order(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            source_a = root / "source-a"
            source_b = root / "source-b"
            for path in (root, source_a, source_b):
                path.mkdir()
            for path in (source_a, source_b):
                (path / "pyproject.toml").write_text(
                    '[project]\nname = "local"\n', encoding="utf-8"
                )
            config = ProjectRecipeConfig(
                root=root,
                package="source-b",
                extra_packages="source-a",
                python="python",
            )
            entered: list[Path] = []

            def record_lock(path: Path):
                entered.append(path)
                return nullcontext()

            with (
                patch.object(project_recipes, "install_lock", side_effect=record_lock),
                patch.object(
                    project_recipes,
                    "run_command",
                ),
            ):
                project_recipes.install(config)
        self.assertEqual(
            [config.resolved_venv, source_a.resolve(), source_b.resolve()], entered
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

    @unittest.skipIf(
        os.name == "nt", "Windows symlink privilege is environment-dependent"
    )
    def test_project_recipe_clean_unlinks_output_symlink_without_traversal(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            marker = outside / "preserved"
            marker.write_text("x", encoding="utf-8")
            (root / "site").symlink_to(outside, target_is_directory=True)
            project_recipes.clean(ProjectRecipeConfig(root=root))
            self.assertFalse((root / "site").exists())
            self.assertEqual("x", marker.read_text(encoding="utf-8"))

    def test_project_recipe_rejects_destructive_venv_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            marker = outside / "preserved"
            marker.write_text("x", encoding="utf-8")
            for venv in (Path("."), outside, Path("../outside")):
                with self.subTest(venv=venv), self.assertRaises(ProjectRecipeError):
                    project_recipes.dist_clean(
                        ProjectRecipeConfig(root=root, venv=venv)
                    )
            self.assertEqual("x", marker.read_text(encoding="utf-8"))

    def test_project_recipe_free_port_rejects_invalid_port(self) -> None:
        with self.assertRaises(ProjectRecipeError):
            project_recipes.free_port(ProjectRecipeConfig(port="70000"))

    def test_project_recipe_rejects_malformed_listener_process_ids(self) -> None:
        with self.assertRaises(ProjectRecipeError):
            project_recipes._parse_pid_lines("1234 invalid")

    def test_linker_rejects_nonpositive_limits(self) -> None:
        valid = {
            "min_phrase_chars": 4,
            "max_links_per_page": 512,
            "max_links_per_target": 2,
        }
        for name in valid:
            with self.subTest(name=name), self.assertRaises(JustdocsLinkerError):
                _validate_linker_limits(valid | {name: 0})

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
        self.assertIn(
            "const setSidebarCollapsed = (side, collapsed, persist = true)", script
        )
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
        self.assertIn("FEATURES.search", script)
        self.assertIn("FEATURES.mermaid", script)
        self.assertIn("FEATURES.codeCopy", script)
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
            "justdocs projects init",
            "justdocs projects check",
            "justdocs version",
            "justdocs check-update",
            "justdocs update",
            "just global-install",
            "just dist",
            "JUSTDOCS_GLOBAL_PYTHON",
            "GlobalCliError",
            "ProjectRecipeError",
            "UpdateCheckError",
            "UpdateSourceEmpty",
            "UpdateInstallError",
            "install.sh",
            "install.ps1",
            "curl -fsSL",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
            "isolated global command environment",
            ".github/actions/build-dist/action.yml",
            ".github/actions/release-assets/action.yml",
            "pypa/gh-action-pypi-publish",
            "PYPI_API_TOKEN",
            "PYPI_TRUSTED_PUBLISHING",
            "SHA256SUMS.txt",
            "3.14t",
            "packaging>=24",
            "ThemeAssetError",
            "TemplateAssetError",
            "ProjectJustfileExistsError",
            "ProjectJustfileInvalidPackageError",
            "ProjectJustfileWriteError",
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
            "Service Discovery",
            "Deployment Guide",
            "Traffic Policy",
            "justdocs project ",
            "justdocs init ",
            "justdocs version --check",
            "just install-global",
            "just uninstall-global",
        )
        for term in stale_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, combined)

    def test_relative_url_uses_current_page_directory(self) -> None:
        self.assertEqual(
            "../concepts/service-discovery.md",
            _relative_url(
                "guides/deployment-guide.md", "concepts/service-discovery.md"
            ),
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
            LinkTarget(
                "Project Setup", "guides/project-setup.md", "guides/project-setup.md"
            ),
            LinkTarget(
                "Smart Links",
                "guides/advanced/smart-links.md",
                "guides/advanced/smart-links.md",
            ),
        )
        linked = _smart_link_markdown(markdown, "index.md", "index.md", targets, 8)
        self.assertIn(
            "| [Theme Configuration](concepts/theme-configuration.md) |", linked
        )
        self.assertIn("[Project Setup](guides/project-setup.md) consumes", linked)
        self.assertIn(
            "[Theme Configuration](concepts/theme-configuration.md) remains", linked
        )
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
            LinkTarget(
                "P1-0008",
                "actions/P1/P1-0008-create-stackgraph-model-tests.md",
                "actions/P1/P1-0008-create-stackgraph-model-tests.md",
            ),
            LinkTarget(
                "P2-0002",
                "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md",
                "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md",
            ),
            LinkTarget(
                "P8-0020",
                "actions/P8/P8-0020-add-docs-freshness-test.md",
                "actions/P8/P8-0020-add-docs-freshness-test.md",
            ),
        )
        linked = _smart_link_markdown(
            markdown,
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            targets,
            16,
        )
        self.assertIn(
            "[`P1-0008`](../P1/P1-0008-create-stackgraph-model-tests.md)", linked
        )
        self.assertIn(
            "[`P2-0002`](P2-0002-create-mermaid-parser-package-boundary.md)", linked
        )
        self.assertIn("[`P8-0020`](../P8/P8-0020-add-docs-freshness-test.md)", linked)
        self.assertIn("action: P1-0008", linked)


if __name__ == "__main__":
    unittest.main()
