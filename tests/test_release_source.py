from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release/release-source.py"
CONTROL = "a" * 40
TARGET = "b" * 40
DEFAULT_HEAD = "c" * 40


class Repository:
    def __init__(self, error_type):
        self.error_type = error_type
        self.calls = []
        self.admitted = True
        self.metadata = '[project]\nversion = "1.2.3"\n'
        self.size = None
        self.archive_name = "pyproject.toml"
        self.archive_link = None

    def git(self, *args):
        self.calls.append(args)
        if args[0] in {"check-ref-format", "fetch"}:
            return ""
        if args == ("rev-parse", "--show-prefix"):
            return ""
        if args[:2] == ("rev-parse", "--verify"):
            if args[2] == "HEAD^{commit}":
                return CONTROL
            if args[2].startswith("refs/remotes/"):
                return DEFAULT_HEAD
            return TARGET
        if args[0] == "merge-base":
            if not self.admitted:
                raise self.error_type("source is outside the default branch")
            return ""
        if args[0] == "cat-file":
            return str(
                self.size if self.size is not None else len(self.metadata.encode())
            )
        if args[:3] == ("show", "-s", "--format=%ct"):
            return "1234567890"
        if args[0] == "show":
            return self.metadata
        if args[0] == "archive":
            archive = Path(args[2].removeprefix("--output="))
            with tarfile.open(archive, "w:") as stream:
                member = tarfile.TarInfo(self.archive_name)
                if self.archive_link is not None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = self.archive_link
                    stream.addfile(member)
                else:
                    payload = self.metadata.encode()
                    member.size = len(payload)
                    stream.addfile(member, io.BytesIO(payload))
            return ""
        raise AssertionError(f"unexpected Git operation: {args}")


class GitRepository:
    def __init__(self, root):
        self.origin = root / "origin"
        self.checkout = root / "checkout"
        self.origin.mkdir()
        self.environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GIT_")
        } | {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Release Test",
            "GIT_AUTHOR_EMAIL": "release@example.invalid",
            "GIT_COMMITTER_NAME": "Release Test",
            "GIT_COMMITTER_EMAIL": "release@example.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
        self.git(self.origin, "init", "--initial-branch=trunk")
        self.metadata = '[project]\nversion = "1.2.3"\n'
        (self.origin / "pyproject.toml").write_text(self.metadata, encoding="utf-8")
        self.git(self.origin, "add", "pyproject.toml")
        self.git(self.origin, "commit", "-m", "Add release source")
        self.selected = self.git(self.origin, "rev-parse", "HEAD")
        (self.origin / "pyproject.toml").write_text(
            '[project]\nversion = "1.2.4"\n', encoding="utf-8"
        )
        self.environment |= {
            "GIT_AUTHOR_DATE": "2000-01-02T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-02T00:00:00+00:00",
        }
        self.git(self.origin, "add", "pyproject.toml")
        self.git(self.origin, "commit", "-m", "Advance control source")
        self.head = self.git(self.origin, "rev-parse", "HEAD")
        self.git(
            self.origin, "clone", "--no-local", str(self.origin), str(self.checkout)
        )

    def git(self, directory, *arguments):
        return subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "commit.gpgsign=false",
                *arguments,
            ],
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()


@unittest.skipIf(sys.version_info < (3, 12), "release tooling runs on Python 3.12+")
class ReleaseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("release_source_tests", SCRIPT)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.repo = Repository(self.module.ReleaseSourceError)
        self.read_only_git = self.module._git
        self.enterContext(patch.object(self.module, "_git", self.repo.git))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "DEFAULT_BRANCH": "trunk",
                    "EVENT_SHA": CONTROL,
                    "EVENT_NAME": "workflow_dispatch",
                    "REF_TYPE": "branch",
                    "REF_NAME": "trunk",
                    "INPUT_TAG": "v1.2.3",
                },
            )
        )

    def test_manual_release_reads_target_metadata_after_ancestry_admission(self):
        result = self.module._release()
        self.assertEqual(TARGET, result["release_sha"])
        self.assertEqual(TARGET, result["release_ref"])
        self.assertEqual("v1.2.3", result["tag"])
        self.assertEqual("false", result["prerelease"])
        self.assertEqual("1234567890", result["source_date_epoch"])
        admission = self.repo.calls.index(
            ("merge-base", "--is-ancestor", TARGET, DEFAULT_HEAD)
        )
        blob = self.repo.calls.index(("show", f"{TARGET}:pyproject.toml"))
        self.assertLess(admission, blob)
        self.assertFalse(
            any(call[0] in {"checkout", "switch", "reset"} for call in self.repo.calls)
        )

    def test_unreviewed_tag_is_rejected_before_metadata_access(self):
        self.repo.admitted = False
        with self.assertRaisesRegex(self.module.ReleaseSourceError, "outside"):
            self.module._release()
        self.assertFalse(
            any(call[0] in {"show", "cat-file"} for call in self.repo.calls)
        )

    def test_release_tag_and_package_version_must_match(self):
        self.repo.metadata = '[project]\nversion = "9.9.9"\n'
        with self.assertRaisesRegex(
            self.module.ReleaseSourceError, "target package version"
        ):
            self.module._release()

    def test_prerelease_metadata_is_preserved(self):
        self.repo.metadata = '[project]\nversion = "1.2.3rc1"\n'
        with patch.dict(os.environ, {"INPUT_TAG": "v1.2.3rc1"}):
            self.assertEqual("true", self.module._release()["prerelease"])

    def test_unsafe_or_noncanonical_tag_is_rejected_before_fetch(self):
        for value in (
            "main",
            "--upload-pack=evil",
            "v1.2.3\nx=1",
            "v1!1.2.3",
            "v1.2.3+local",
            "v01.2.3",
        ):
            with self.subTest(tag=value), patch.dict(os.environ, {"INPUT_TAG": value}):
                self.repo.calls.clear()
                with self.assertRaises(self.module.ReleaseSourceError):
                    self.module._release()
                self.assertFalse(any(call[0] == "fetch" for call in self.repo.calls))

    def test_dispatch_requires_default_branch_control_ref(self):
        for overrides in ({"REF_NAME": "feature"}, {"REF_TYPE": "tag"}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides):
                with self.assertRaisesRegex(
                    self.module.ReleaseSourceError, "default branch"
                ):
                    self.module._release()

    def test_control_checkout_must_match_event_sha(self):
        with patch.dict(os.environ, {"EVENT_SHA": "d" * 40}):
            with self.assertRaisesRegex(
                self.module.ReleaseSourceError, "control checkout"
            ):
                self.module._release()

    def test_control_checkout_rejects_parent_repository_discovery(self):
        def nested_git(*arguments):
            if arguments == ("rev-parse", "--show-prefix"):
                return "release-source/"
            return self.repo.git(*arguments)

        with patch.object(self.module, "_git", nested_git):
            with self.assertRaisesRegex(
                self.module.ReleaseSourceError, "repository root"
            ):
                self.module._export(TARGET, Path("source"))
        self.assertFalse(any(call[0] == "fetch" for call in self.repo.calls))

    def test_push_tag_is_bound_to_event_commit(self):
        with patch.dict(
            os.environ, {"EVENT_NAME": "push", "REF_TYPE": "tag", "REF_NAME": "v1.2.3"}
        ):
            with self.assertRaisesRegex(self.module.ReleaseSourceError, "push commit"):
                self.module._release()
            with (
                patch.dict(os.environ, {"EVENT_SHA": TARGET}),
                patch.object(
                    self.module, "_control_identity", return_value=("trunk", TARGET)
                ),
            ):
                self.assertEqual(TARGET, self.module._release()["release_sha"])

    def test_invalid_metadata_is_rejected(self):
        for metadata in ("not TOML", "[project]\n", "[project]\nversion = 123\n"):
            with self.subTest(metadata=metadata):
                self.repo.metadata = metadata
                with self.assertRaises(self.module.ReleaseSourceError):
                    self.module._release()

    def test_metadata_size_is_bounded_before_blob_read(self):
        for size in (0, self.module.MAX_PROJECT_BYTES + 1):
            with self.subTest(size=size):
                self.repo.size = size
                self.repo.calls.clear()
                with self.assertRaisesRegex(self.module.ReleaseSourceError, "1 MiB"):
                    self.module._release()
                self.assertNotIn(("show", f"{TARGET}:pyproject.toml"), self.repo.calls)

    def test_latest_ref_changes_fail_closed(self):
        with self.assertRaisesRegex(self.module.ReleaseSourceError, "changed"):
            self.module._latest()
        with patch.object(self.module, "_default_head", return_value=CONTROL):
            result = self.module._latest()
        self.assertEqual(CONTROL, result["release_sha"])
        self.assertEqual(CONTROL[:12], result["release_short_sha"])

    def test_invalid_source_sha_is_rejected_without_git_access(self):
        for value in ("main", "a" * 39, "A" * 40, "a" * 40 + "\n"):
            with self.subTest(value=value):
                self.repo.calls.clear()
                with self.assertRaises(self.module.ReleaseSourceError):
                    self.module._export(value, Path("release-source"))
                self.assertEqual([], self.repo.calls)

    def test_export_contains_only_target_tree_data(self):
        with TemporaryDirectory() as directory:
            with patch.object(self.module.Path, "cwd", return_value=Path(directory)):
                target = Path(directory) / "source"
                result = self.module._export(TARGET, target)
                self.assertEqual(
                    self.repo.metadata, (target / "pyproject.toml").read_text()
                )
                self.assertFalse((target / ".git").exists())
                self.assertEqual({"source_date_epoch": "1234567890"}, result)
                self.assertEqual([target], list(Path(directory).iterdir()))

    def test_export_rejects_unreviewed_source_without_creating_files(self):
        self.repo.admitted = False
        with TemporaryDirectory() as directory:
            with patch.object(self.module.Path, "cwd", return_value=Path(directory)):
                with self.assertRaises(self.module.ReleaseSourceError):
                    self.module._export(TARGET, Path(directory) / "source")
                self.assertEqual([], list(Path(directory).iterdir()))

    def test_export_matches_actual_git_tree_without_mutating_repository(self):
        with TemporaryDirectory() as directory:
            fixture = GitRepository(Path(directory).resolve())
            target = fixture.checkout / "source"

            def admitted_git(*arguments):
                return self.read_only_git("-C", str(fixture.checkout), *arguments)

            with (
                patch.object(self.module, "_git", admitted_git),
                patch.object(self.module.Path, "cwd", return_value=fixture.checkout),
                patch.dict(os.environ, {"EVENT_SHA": fixture.head}),
            ):
                result = self.module._export(fixture.selected, target)
            self.assertEqual(fixture.metadata, (target / "pyproject.toml").read_text())
            self.assertFalse((target / ".git").exists())
            self.assertEqual(
                fixture.git(
                    fixture.checkout, "show", "-s", "--format=%ct", fixture.selected
                ),
                result["source_date_epoch"],
            )
            self.assertNotEqual(
                fixture.git(
                    fixture.checkout, "show", "-s", "--format=%ct", fixture.head
                ),
                result["source_date_epoch"],
            )
            self.assertEqual(
                fixture.head, fixture.git(fixture.checkout, "rev-parse", "HEAD")
            )
            self.assertIn(
                'version = "1.2.4"',
                (fixture.checkout / "pyproject.toml").read_text(),
            )
            with (
                patch.object(
                    self.module,
                    "_git",
                    lambda *args: self.read_only_git("-C", str(target), *args),
                ),
                patch.object(self.module.Path, "cwd", return_value=target),
                patch.dict(os.environ, {"EVENT_SHA": fixture.head}),
                self.assertRaisesRegex(
                    self.module.ReleaseSourceError, "repository root"
                ),
            ):
                self.module._export(fixture.selected, target / "nested")
            self.assertEqual([target / "pyproject.toml"], list(target.iterdir()))

    @unittest.skipIf(os.name == "nt", "workspace alias uses a POSIX symlink")
    def test_export_accepts_workspace_alias_without_allowing_linked_children(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            alias = root / "alias"
            alias.symlink_to(workspace, target_is_directory=True)
            with patch.object(self.module.Path, "cwd", return_value=alias):
                for destination in (
                    alias / "absolute",
                    Path("relative"),
                    workspace / "canonical",
                ):
                    with self.subTest(destination=destination):
                        self.module._export(TARGET, destination)
                        self.assertEqual(
                            self.repo.metadata,
                            (
                                workspace / destination.name / "pyproject.toml"
                            ).read_text(),
                        )
                link = workspace / "link"
                link.symlink_to(workspace, target_is_directory=True)
                with self.assertRaises(self.module.ReleaseSourceError):
                    self.module._export(TARGET, alias / "link" / "source")
                self.assertFalse((workspace / "source").exists())

    def test_timestamp_failure_does_not_publish_export_directory(self):
        with (
            TemporaryDirectory() as directory,
            patch.object(self.module.Path, "cwd", return_value=Path(directory)),
            patch.object(
                self.module,
                "_epoch",
                side_effect=self.module.ReleaseSourceError("invalid timestamp"),
            ),
        ):
            with self.assertRaisesRegex(self.module.ReleaseSourceError, "timestamp"):
                self.module._export(TARGET, Path(directory) / "source")
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_export_rejects_existing_or_escaping_destination(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing"
            existing.mkdir()
            existing_file = root / "file"
            existing_file.touch()
            with patch.object(self.module.Path, "cwd", return_value=root):
                for destination in (
                    root,
                    existing,
                    existing_file,
                    root.parent / "outside",
                    root.parent / f"{root.name}-adjacent" / "source",
                    Path("../outside"),
                    root / "existing" / ".." / "source",
                ):
                    with (
                        self.subTest(destination=destination),
                        self.assertRaises(self.module.ReleaseSourceError),
                    ):
                        self.module._export(TARGET, destination)
            self.assertEqual({existing, existing_file}, set(root.iterdir()))

    @unittest.skipIf(os.name == "nt", "source link confinement requires POSIX symlinks")
    def test_export_rejects_linked_destinations_and_cycles(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            links = {
                "internal": root,
                "external": root.parent,
                "dangling": root / "missing",
                "cycle": root / "cycle",
            }
            for name, target in links.items():
                (root / name).symlink_to(target, target_is_directory=True)
            with patch.object(self.module.Path, "cwd", return_value=root):
                for name in links:
                    with (
                        self.subTest(link=name),
                        self.assertRaises(self.module.ReleaseSourceError),
                    ):
                        self.module._export(TARGET, root / name / "source")
            self.assertEqual(set(links), {item.name for item in root.iterdir()})

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    def test_export_rejects_directory_junction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            junction = root / "junction"
            subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
            with (
                patch.object(self.module.Path, "cwd", return_value=root),
                self.assertRaises(self.module.ReleaseSourceError),
            ):
                self.module._export(TARGET, junction / "source")
            self.assertEqual([], list(target.iterdir()))

    def test_archive_traversal_and_external_links_are_rejected_and_cleaned(self):
        for name, link in (("../escaped", None), ("link", "../../escaped")):
            with self.subTest(name=name), TemporaryDirectory() as directory:
                self.repo.archive_name = name
                self.repo.archive_link = link
                with patch.object(
                    self.module.Path, "cwd", return_value=Path(directory)
                ):
                    with self.assertRaisesRegex(
                        self.module.ReleaseSourceError, "archive"
                    ):
                        self.module._export(TARGET, Path(directory) / "source")
                self.assertEqual([], list(Path(directory).iterdir()))

    def test_isolated_cli_does_not_import_candidate_startup_modules(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            (root / "sitecustomize.py").write_text(
                f"from pathlib import Path; Path({str(marker)!r}).touch()\n"
            )
            result = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--help"],
                cwd=root,
                env=os.environ | {"PYTHONPATH": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(marker.exists())

    def test_cli_failure_emits_no_outputs_or_traceback(self):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", [str(SCRIPT), "resolve"]),
            patch.object(
                self.module,
                "_release",
                side_effect=self.module.ReleaseSourceError("rejected"),
            ),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            self.assertEqual(1, self.module.main())
        self.assertEqual("", output.getvalue())
        self.assertEqual("release source rejected: rejected\n", errors.getvalue())


class ReleaseWorkflowTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Bash composite preflight")
    def test_invalid_target_fails_before_legacy_recovery(self):
        action = yaml.safe_load(
            (ROOT / ".github/actions/release-assets/action.yml").read_text()
        )
        step = next(
            step
            for step in action["runs"]["steps"]
            if step.get("name") == "Preflight release transaction"
        )
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", "-c", step["run"]],
                cwd=directory,
                env=os.environ | {"TARGET_SHA": "--invalid", "RELEASE_TAG": "latest"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("invalid target_sha", result.stderr)
            self.assertNotIn("python", result.stderr)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_every_release_checkout_uses_event_identity_without_credentials(self):
        for name in ("release", "latest", "reusable-build-python-package"):
            value = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
            self.assertNotIn("cache-mode", value)
            for job in value["jobs"].values():
                for step in job.get("steps", []):
                    with self.subTest(workflow=name, step=step.get("name")):
                        self.assertNotIn("cache", step.get("with", {}))
                        if step.get("uses", "").startswith("actions/checkout@"):
                            self.assertEqual("${{ github.sha }}", step["with"]["ref"])
                            self.assertIs(False, step["with"]["persist-credentials"])

    def test_build_tests_exported_source_before_building_with_trusted_script(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/reusable-build-python-package.yml").read_text()
        )
        job = workflow["jobs"]["build"]
        steps = job["steps"]
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index("Export admitted build source"),
            names.index("Test admitted build source"),
        )
        self.assertLess(
            names.index("Test admitted build source"),
            names.index("Build distributions"),
        )
        test = steps[names.index("Test admitted build source")]
        build = steps[names.index("Build distributions")]
        self.assertEqual("release-source", test["working-directory"])
        self.assertEqual("release-source", build["with"]["source_dir"])
        self.assertEqual(
            "${{ steps.source.outputs.source_date_epoch }}",
            build["env"]["SOURCE_DATE_EPOCH"],
        )
        self.assertEqual({"contents": "read"}, workflow["permissions"])
        self.assertNotIn("secrets", job)
        action = yaml.safe_load(
            (ROOT / ".github/actions/build-dist/action.yml").read_text()
        )
        build_step = next(
            step
            for step in action["runs"]["steps"]
            if step.get("name") == "Build distributions"
        )
        self.assertEqual("${{ inputs.source_dir }}", build_step["working-directory"])
        self.assertTrue(
            build_step["env"]["BUILD_SCRIPT"].startswith("${{ github.action_path }}/")
        )
        self.assertEqual('bash "$BUILD_SCRIPT"', build_step["run"])

    def test_publishers_receive_target_sha_independent_of_control_head(self):
        for name in ("release", "latest"):
            value = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
            steps = value["jobs"]["github-release"]["steps"]
            action = next(
                step
                for step in steps
                if step.get("uses") == "./.github/actions/release-assets"
            )
            self.assertEqual(
                "${{ needs.preflight.outputs.release_sha }}",
                action["with"]["target_sha"],
            )
        source = (ROOT / ".github/actions/release-assets/action.yml").read_text()
        self.assertIn("TARGET_SHA: ${{ inputs.target_sha }}", source)
        self.assertIn('git rev-parse --verify "${TARGET_SHA}^{commit}"', source)
        self.assertNotIn("git rev-parse --verify 'HEAD^{commit}'", source)
