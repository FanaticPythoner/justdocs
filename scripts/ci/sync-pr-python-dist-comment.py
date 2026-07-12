#!/usr/bin/env python3
"""Synchronize one trusted PR comment for CI-built Python distributions."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API_VERSION = "2022-11-28"
ARTIFACT_NAME = "justdocs-python-dist"
COMMENT_MARKER = "<!-- justdocs-pr-python-dist"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{40}$")


class DistributionCommentError(RuntimeError):
    """Report an invalid workflow run or GitHub API response."""


@dataclass(frozen=True)
class RunContext:
    """Store validated PR workflow run identity."""

    run_id: int
    run_attempt: int
    pull_request: int
    head_sha: str
    conclusion: str
    html_url: str


@dataclass(frozen=True)
class Artifact:
    """Store validated distribution artifact metadata."""

    artifact_id: int
    size: int
    digest: str
    expires_at: str


class GitHubClient:
    """Read and mutate bounded GitHub REST resources."""

    def __init__(self, repository: str, token: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
            raise DistributionCommentError("invalid GitHub repository")
        if not token or any(
            ord(character) < 0x21 or ord(character) > 0x7E for character in token
        ):
            raise DistributionCommentError("invalid GitHub token")
        self.repository = repository
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "justdocs-pr-distribution-comment",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def request(self, method: str, endpoint: str, payload: object = None) -> object:
        """Return one bounded JSON response from the repository API."""

        data = None
        headers = dict(self._headers)
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        url = f"https://api.github.com/repos/{self.repository}/{endpoint}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError) as error:
            raise DistributionCommentError(
                f"GitHub API request failed: {method} {endpoint}"
            ) from error
        if len(body) > MAX_RESPONSE_BYTES:
            raise DistributionCommentError("GitHub API response exceeds 4 MiB")
        if not body:
            return None
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DistributionCommentError(
                "GitHub API response is invalid JSON"
            ) from error


def _object(value: object, label: str) -> dict[str, object]:
    """Return a JSON object with a typed failure label."""

    if not isinstance(value, dict):
        raise DistributionCommentError(f"invalid {label}")
    return value


def _positive_integer(value: object, label: str) -> int:
    """Return a positive integer field."""

    if type(value) is not int or value <= 0:
        raise DistributionCommentError(f"invalid {label}")
    return value


def _load_context(path: Path) -> RunContext:
    """Load and validate one completed pull-request CI workflow run."""

    try:
        size = path.stat(follow_symlinks=False).st_size
    except OSError as error:
        raise DistributionCommentError(
            "workflow event payload is unavailable"
        ) from error
    if size <= 0 or size > MAX_RESPONSE_BYTES or path.is_symlink():
        raise DistributionCommentError("workflow event payload is invalid")
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DistributionCommentError("workflow event payload is invalid") from error
    run = _object(_object(event, "workflow event").get("workflow_run"), "workflow run")
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list) or len(pull_requests) != 1:
        raise DistributionCommentError("workflow run must identify one pull request")
    pull_request = _object(pull_requests[0], "pull request")
    head_sha = run.get("head_sha")
    conclusion = run.get("conclusion")
    html_url = run.get("html_url")
    run_id = _positive_integer(run.get("id"), "workflow run ID")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    expected_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if (
        run.get("name") != "CI"
        or run.get("event") != "pull_request"
        or run.get("status") != "completed"
        or not isinstance(head_sha, str)
        or SHA.fullmatch(head_sha) is None
        or conclusion
        not in {"success", "failure", "cancelled", "timed_out", "action_required"}
        or html_url != expected_url
    ):
        raise DistributionCommentError("workflow run identity is invalid")
    return RunContext(
        run_id=run_id,
        run_attempt=_positive_integer(run.get("run_attempt"), "workflow run attempt"),
        pull_request=_positive_integer(
            pull_request.get("number"), "pull request number"
        ),
        head_sha=head_sha,
        conclusion=conclusion,
        html_url=html_url,
    )


def _artifact(client: GitHubClient, context: RunContext) -> Artifact:
    """Return the unique nonexpired distribution artifact for a successful run."""

    response = _object(
        client.request(
            "GET",
            f"actions/runs/{context.run_id}/artifacts?per_page=100",
        ),
        "workflow artifacts",
    )
    values = response.get("artifacts")
    if not isinstance(values, list):
        raise DistributionCommentError("workflow artifact inventory is invalid")
    matches = [
        _object(value, "workflow artifact")
        for value in values
        if isinstance(value, dict) and value.get("name") == ARTIFACT_NAME
    ]
    if len(matches) != 1:
        raise DistributionCommentError(
            f"workflow run must contain one '{ARTIFACT_NAME}' artifact"
        )
    value = matches[0]
    digest = value.get("digest")
    expires_at = value.get("expires_at")
    size = value.get("size_in_bytes")
    if (
        value.get("expired") is not False
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest or "") is None
        or not isinstance(expires_at, str)
        or type(size) is not int
        or size <= 0
    ):
        raise DistributionCommentError("workflow artifact metadata is invalid")
    return Artifact(
        artifact_id=_positive_integer(value.get("id"), "workflow artifact ID"),
        size=size,
        digest=digest,
        expires_at=expires_at,
    )


def _render(context: RunContext, artifact: Artifact | None) -> str:
    """Render one deterministic PR distribution comment body."""

    short_sha = context.head_sha[:12]
    marker = "\n".join(
        (
            COMMENT_MARKER,
            f"run-id: {context.run_id}",
            f"run-attempt: {context.run_attempt}",
            f"head-sha: {context.head_sha}",
            "-->",
        )
    )
    if context.conclusion == "success" and artifact is not None:
        download = f"{context.html_url}/artifacts/{artifact.artifact_id}"
        return "\n".join(
            (
                marker,
                "### PR Python distributions: ready",
                "",
                f"Full CI passed for [`{short_sha}`](https://github.com/"
                f"{os.environ['GITHUB_REPOSITORY']}/commit/{context.head_sha}).",
                "",
                f"[Download wheel, source archive, installers, and checksum manifest]({download})",
                "",
                "Security: packages contain unreviewed pull-request code. Installation belongs "
                "in an isolated disposable virtual environment without production credentials.",
                "",
                f"Artifact bytes: `{artifact.size}`  ",
                f"Artifact digest: `{artifact.digest}`  ",
                f"Expires: `{artifact.expires_at}`  ",
                f"[Workflow run]({context.html_url})",
            )
        )
    return "\n".join(
        (
            marker,
            "### PR Python distributions: unavailable",
            "",
            f"CI `{context.conclusion}` for [`{short_sha}`](https://github.com/"
            f"{os.environ['GITHUB_REPOSITORY']}/commit/{context.head_sha}).",
            "",
            f"[Workflow run]({context.html_url})",
        )
    )


def _comments(client: GitHubClient, pull_request: int) -> tuple[dict[str, object], ...]:
    """Return all issue comments for one pull request."""

    comments: list[dict[str, object]] = []
    for page in range(1, 101):
        response = client.request(
            "GET",
            f"issues/{pull_request}/comments?per_page=100&page={page}",
        )
        if not isinstance(response, list):
            raise DistributionCommentError("pull request comment inventory is invalid")
        comments.extend(_object(value, "pull request comment") for value in response)
        if len(response) < 100:
            return tuple(comments)
    raise DistributionCommentError(
        "pull request comment inventory exceeds 10,000 entries"
    )


def _synchronize(client: GitHubClient, context: RunContext, body: str) -> None:
    """Create or replace the single managed pull-request comment."""

    managed = []
    for comment in _comments(client, context.pull_request):
        author = comment.get("user")
        if (
            isinstance(author, dict)
            and author.get("login") == "github-actions[bot]"
            and author.get("type") == "Bot"
            and isinstance(comment.get("body"), str)
            and COMMENT_MARKER in comment["body"]
        ):
            managed.append(comment)
    if len(managed) > 1:
        raise DistributionCommentError("multiple managed distribution comments exist")
    if managed:
        existing_body = managed[0].get("body")
        run_match = re.search(
            r"(?m)^run-id: ([1-9][0-9]*)$",
            existing_body if isinstance(existing_body, str) else "",
        )
        attempt_match = re.search(
            r"(?m)^run-attempt: ([1-9][0-9]*)$",
            existing_body if isinstance(existing_body, str) else "",
        )
        if (run_match is None) != (attempt_match is None):
            raise DistributionCommentError("managed comment identity is incomplete")
        if run_match is not None and attempt_match is not None:
            existing_identity = (int(run_match.group(1)), int(attempt_match.group(1)))
            current_identity = (context.run_id, context.run_attempt)
            if existing_identity > current_identity:
                _delete_run_artifacts(client, context.run_id)
                return
            if existing_identity < current_identity:
                _delete_run_artifacts(client, existing_identity[0])
        comment_id = _positive_integer(managed[0].get("id"), "comment ID")
        client.request("PATCH", f"issues/comments/{comment_id}", {"body": body})
    else:
        client.request(
            "POST",
            f"issues/{context.pull_request}/comments",
            {"body": body},
        )


def _closed_body(pull_request: int, head_sha: str) -> str:
    """Render the terminal comment for a closed pull request."""

    return "\n".join(
        (
            COMMENT_MARKER,
            f"head-sha: {head_sha}",
            "-->",
            "### PR Python distributions: unavailable",
            "",
            f"The artifact for pull request #{pull_request} was removed when the "
            "pull request closed.",
        )
    )


def _delete_run_artifacts(client: GitHubClient, run_id: int) -> None:
    """Delete distribution artifacts bound to one workflow run."""

    response = _object(
        client.request("GET", f"actions/runs/{run_id}/artifacts?per_page=100"),
        "workflow artifacts",
    )
    artifacts = response.get("artifacts")
    if not isinstance(artifacts, list):
        raise DistributionCommentError("workflow artifact inventory is invalid")
    for artifact in artifacts:
        candidate = _object(artifact, "workflow artifact")
        if candidate.get("name") == ARTIFACT_NAME:
            artifact_id = _positive_integer(candidate.get("id"), "artifact ID")
            client.request("DELETE", f"actions/artifacts/{artifact_id}")


def _pull_request(client: GitHubClient, pull_request: int) -> dict[str, object]:
    """Return a repository-bound pull request document."""

    value = _object(client.request("GET", f"pulls/{pull_request}"), "pull request")
    base = _object(value.get("base"), "pull request base")
    base_repository = _object(base.get("repo"), "base repository")
    if (
        value.get("number") != pull_request
        or value.get("state") not in {"open", "closed"}
        or base_repository.get("full_name") != client.repository
    ):
        raise DistributionCommentError("pull request identity changed")
    return value


def _close(
    client: GitHubClient,
    pull_request: int,
    head_sha: str,
    run_id: int | None = None,
) -> None:
    """Remove run artifacts and terminate the managed comment for a closed PR."""

    if pull_request <= 0 or SHA.fullmatch(head_sha) is None:
        raise DistributionCommentError("invalid closed pull request identity")
    value = _pull_request(client, pull_request)
    head = _object(value.get("head"), "pull request head")
    if (
        value.get("state") != "closed"
        or head.get("sha") != head_sha
    ):
        raise DistributionCommentError("closed pull request identity changed")
    managed = [
        comment
        for comment in _comments(client, pull_request)
        if isinstance(comment.get("body"), str)
        and COMMENT_MARKER in comment["body"]
        and isinstance(comment.get("user"), dict)
        and comment["user"].get("login") == "github-actions[bot]"
        and comment["user"].get("type") == "Bot"
    ]
    if len(managed) > 1:
        raise DistributionCommentError("multiple managed distribution comments exist")
    run_ids = {run_id} if run_id is not None else set()
    if managed:
        body = managed[0]["body"]
        match = re.search(r"(?m)^run-id: ([1-9][0-9]*)$", body)
        if match is not None:
            run_ids.add(int(match.group(1)))
    for bound_run_id in sorted(run_ids):
        _delete_run_artifacts(client, bound_run_id)
    if managed:
        comment_id = _positive_integer(managed[0].get("id"), "comment ID")
        client.request(
            "PATCH",
            f"issues/comments/{comment_id}",
            {"body": _closed_body(pull_request, head_sha)},
        )


def _parser() -> argparse.ArgumentParser:
    """Build the distribution comment argument parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--closed-pull-request", type=int)
    parser.add_argument("--head-sha")
    return parser


def main() -> int:
    """Synchronize the PR distribution comment and return a process exit code."""

    try:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        client = GitHubClient(repository, os.environ.get("GH_TOKEN", ""))
        arguments = _parser().parse_args()
        if arguments.closed_pull_request is not None:
            if arguments.head_sha is None:
                raise DistributionCommentError(
                    "closed pull request head SHA is missing"
                )
            _close(client, arguments.closed_pull_request, arguments.head_sha)
            print(
                f"PR #{arguments.closed_pull_request} distribution artifacts removed"
            )
            return 0
        if arguments.head_sha is not None:
            raise DistributionCommentError("head SHA requires a closed pull request")
        context = _load_context(Path(os.environ.get("GITHUB_EVENT_PATH", "")))
        pull_request = _pull_request(client, context.pull_request)
        head = _object(pull_request.get("head"), "pull request head")
        if pull_request.get("state") == "closed":
            if head.get("sha") == context.head_sha:
                _close(
                    client,
                    context.pull_request,
                    context.head_sha,
                    context.run_id,
                )
            else:
                _delete_run_artifacts(client, context.run_id)
            print(f"PR #{context.pull_request} is closed; distribution removed")
            return 0
        if head.get("sha") != context.head_sha:
            _delete_run_artifacts(client, context.run_id)
            print(
                f"PR #{context.pull_request} workflow run is stale; "
                "distribution removed"
            )
            return 0
        artifact = (
            _artifact(client, context) if context.conclusion == "success" else None
        )
        if context.conclusion != "success":
            _delete_run_artifacts(client, context.run_id)
        _synchronize(client, context, _render(context, artifact))
    except (OSError, DistributionCommentError) as error:
        print(f"PR distribution comment failed: {error}", file=sys.stderr)
        return 1
    print(f"PR #{context.pull_request} distribution comment synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
