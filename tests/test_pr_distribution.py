from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import yaml


REPOSITORY = "FanaticPythoner/justdocs"
HEAD_SHA = "a" * 40


def pull_request(number: int = 137) -> dict[str, object]:
    """Return one commit-associated pull request with a bound source identity."""

    return {
        "number": number,
        "state": "open",
        "head": {
            "ref": "feature",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "base": {"repo": {"full_name": REPOSITORY}},
    }


class PrDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path("scripts/ci/sync-pr-python-dist-comment.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "pr_distribution_tests", path
        )
        assert specification is not None and specification.loader is not None
        cls.module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = cls.module
        cls.addClassCleanup(sys.modules.pop, specification.name)
        specification.loader.exec_module(cls.module)

    def setUp(self) -> None:
        self.client = Mock(spec=self.module.GitHubClient)
        self.client.repository = REPOSITORY
        self.client.request.return_value = [pull_request()]
        self.run = {
            "id": 42,
            "run_attempt": 3,
            "name": "CI",
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": HEAD_SHA,
            "head_branch": "feature",
            "head_repository": {"full_name": REPOSITORY},
            "repository": {"full_name": REPOSITORY},
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/42",
            "pull_requests": [],
        }
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.event = Path(directory.name) / "event.json"

    def load_context(self):
        self.event.write_text(json.dumps({"workflow_run": self.run}), encoding="utf-8")
        return self.module._load_context(self.event, self.client)

    def test_empty_event_associations_resolve_through_commit_api(self) -> None:
        context = self.load_context()
        self.assertEqual(
            (42, 3, 137, HEAD_SHA),
            (
                context.run_id,
                context.run_attempt,
                context.pull_request,
                context.head_sha,
            ),
        )
        self.client.request.assert_called_once_with(
            "GET", f"commits/{HEAD_SHA}/pulls?per_page=100&page=1"
        )

    def test_embedded_associations_do_not_override_commit_identity(self) -> None:
        self.run["pull_requests"] = [{"number": 999}]
        self.assertEqual(137, self.load_context().pull_request)

    def test_associations_are_paginated_before_uniqueness_check(self) -> None:
        unrelated = pull_request(999)
        unrelated["head"]["ref"] = "unrelated"
        self.client.request.side_effect = [[unrelated] * 100, [pull_request()]]
        self.assertEqual(137, self.load_context().pull_request)
        self.assertEqual(
            [
                (("GET", f"commits/{HEAD_SHA}/pulls?per_page=100&page={page}"), {})
                for page in (1, 2)
            ],
            self.client.request.call_args_list,
        )

    def test_multiple_matching_pull_requests_are_rejected(self) -> None:
        self.client.request.return_value = [pull_request(), pull_request(138)]
        with self.assertRaisesRegex(
            self.module.DistributionCommentError, "identify one"
        ):
            self.load_context()

    def test_unbound_associations_are_rejected(self) -> None:
        for path, value in (
            (("head", "ref"), "another-branch"),
            (("head", "repo", "full_name"), "unrelated/justdocs"),
            (("base", "repo", "full_name"), "unrelated/justdocs"),
            (("head", "repo"), None),
        ):
            with self.subTest(path=path):
                candidate = pull_request()
                target = candidate
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                self.client.request.return_value = [candidate]
                with self.assertRaisesRegex(
                    self.module.DistributionCommentError, "identify one"
                ):
                    self.load_context()

    def test_fork_source_requires_exact_repository_and_branch(self) -> None:
        candidate = pull_request()
        candidate["head"]["repo"]["full_name"] = "contributor/justdocs"
        self.run["head_repository"]["full_name"] = "contributor/justdocs"
        self.client.request.return_value = [candidate]
        self.assertEqual(137, self.load_context().pull_request)

    def test_invalid_run_identity_is_rejected_before_api_access(self) -> None:
        initial = copy.deepcopy(self.run)
        for key, value in (
            ("id", True),
            ("run_attempt", 0),
            ("name", "Release"),
            ("event", "push"),
            ("status", "in_progress"),
            ("conclusion", None),
            ("head_sha", "../pulls"),
            ("html_url", "https://github.com/unrelated/justdocs/actions/runs/42"),
            ("repository", {"full_name": "unrelated/justdocs"}),
            ("head_branch", ""),
            ("head_repository", None),
        ):
            with self.subTest(key=key):
                self.run = copy.deepcopy(initial)
                self.run[key] = value
                with self.assertRaises(self.module.DistributionCommentError):
                    self.load_context()
        self.client.request.assert_not_called()

    def test_malformed_api_inventory_and_numbers_are_rejected(self) -> None:
        for response in ({}, [None], [pull_request(True)], [pull_request(0)]):
            with self.subTest(response=response):
                self.client.request.return_value = response
                with self.assertRaises(self.module.DistributionCommentError):
                    self.load_context()

    def test_association_enumeration_has_explicit_bound(self) -> None:
        candidate = pull_request()
        candidate["head"]["ref"] = "unrelated"
        self.client.request.return_value = [candidate] * 100
        with self.assertRaisesRegex(self.module.DistributionCommentError, "10,000"):
            self.load_context()
        self.assertEqual(100, self.client.request.call_count)

    def test_api_failure_propagates(self) -> None:
        self.client.request.side_effect = self.module.DistributionCommentError(
            "API failure"
        )
        with self.assertRaisesRegex(
            self.module.DistributionCommentError, "API failure"
        ):
            self.load_context()

    def run_main(self, current_pull_request, artifact=None):
        self.event.write_text(json.dumps({"workflow_run": self.run}), encoding="utf-8")

        def respond(method, endpoint, payload=None):
            if method == "GET" and endpoint.startswith(f"commits/{HEAD_SHA}/pulls?"):
                return [current_pull_request]
            if method == "GET" and endpoint == "pulls/137":
                return current_pull_request
            if method == "GET" and endpoint.startswith("actions/runs/42/artifacts?"):
                return {"artifacts": [] if artifact is None else [artifact]}
            if method == "GET" and endpoint.startswith("issues/137/comments?"):
                return []
            if method == "POST" and endpoint == "issues/137/comments":
                return {"id": 81}
            if method == "DELETE" and endpoint == "actions/artifacts/73":
                return None
            raise AssertionError(f"unexpected request: {method} {endpoint}")

        self.client.request.side_effect = respond
        output, errors = StringIO(), StringIO()
        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": REPOSITORY,
                    "GITHUB_EVENT_PATH": str(self.event),
                    "GH_TOKEN": "fixture-token",
                },
            ),
            patch.object(sys, "argv", ["sync-pr-python-dist-comment.py"]),
            patch.object(self.module, "GitHubClient", return_value=self.client),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            code = self.module.main()
        self.assertEqual(0, code, errors.getvalue())
        self.assertEqual("", errors.getvalue())
        return output.getvalue()

    def test_success_publishes_bound_artifact_from_empty_event_associations(
        self,
    ) -> None:
        artifact = {
            "id": 73,
            "name": self.module.ARTIFACT_NAME,
            "expired": False,
            "size_in_bytes": 4096,
            "digest": "sha256:" + "b" * 64,
            "expires_at": "2026-11-26T00:00:00Z",
        }
        self.run_main(pull_request(), artifact)
        posts = [
            call
            for call in self.client.request.call_args_list
            if call.args[0] == "POST"
        ]
        self.assertEqual(1, len(posts))
        self.assertIn("/actions/runs/42/artifacts/73", posts[0].args[2]["body"])

    def test_closed_pr_resolves_without_embedded_associations_and_cleans_artifact(
        self,
    ) -> None:
        candidate = pull_request()
        candidate["state"] = "closed"
        output = self.run_main(candidate, {"id": 73, "name": self.module.ARTIFACT_NAME})
        self.assertIn("is closed", output)
        self.client.request.assert_any_call("DELETE", "actions/artifacts/73")
        self.assertFalse(
            any(call.args[0] == "POST" for call in self.client.request.call_args_list)
        )

    def test_advanced_pr_head_cleans_stale_run_without_commenting(self) -> None:
        candidate = pull_request()
        candidate["head"]["sha"] = "c" * 40
        output = self.run_main(candidate, {"id": 73, "name": self.module.ARTIFACT_NAME})
        self.assertIn("is stale", output)
        self.client.request.assert_any_call("DELETE", "actions/artifacts/73")
        self.assertFalse(
            any(call.args[0] == "POST" for call in self.client.request.call_args_list)
        )

    def test_failed_ci_cleans_artifact_and_publishes_unavailable(self) -> None:
        self.run["conclusion"] = "failure"
        self.run_main(pull_request(), {"id": 73, "name": self.module.ARTIFACT_NAME})
        self.client.request.assert_any_call("DELETE", "actions/artifacts/73")
        posts = [
            call
            for call in self.client.request.call_args_list
            if call.args[0] == "POST"
        ]
        self.assertEqual(1, len(posts))
        self.assertIn("PR Python distributions: unavailable", posts[0].args[2]["body"])

    def test_workflow_cleanup_permissions_and_source_locks_match(self) -> None:
        publisher = yaml.safe_load(
            Path(".github/workflows/pr-python-dist-comment.yml").read_text(
                encoding="utf-8"
            )
        )["jobs"]["publish"]
        closer = yaml.safe_load(
            Path(".github/workflows/pr-python-dist-lifecycle.yml").read_text(
                encoding="utf-8"
            )
        )["jobs"]["close"]
        self.assertEqual(
            "github.event.workflow_run.event == 'pull_request'", publisher["if"]
        )
        locks = []
        for job, fields in (
            (
                publisher,
                ("workflow_run.head_repository.full_name", "workflow_run.head_branch"),
            ),
            (closer, ("pull_request.head.repo.full_name", "pull_request.head.ref")),
        ):
            self.assertEqual("write", job["permissions"]["actions"])
            self.assertIs(False, job["concurrency"]["cancel-in-progress"])
            self.assertEqual("max", job["concurrency"]["queue"])
            lock = job["concurrency"]["group"]
            for field, symbol in zip(fields, ("source_repository", "source_branch")):
                self.assertIn(f"github.event.{field}", lock)
                lock = lock.replace(f"github.event.{field}", symbol)
            locks.append(lock)
        self.assertEqual(locks[0], locks[1])
