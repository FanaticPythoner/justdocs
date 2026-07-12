#!/usr/bin/env python3
"""Verify a published GitHub Release against local immutable artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{40}$")


class ReleaseVerificationError(RuntimeError):
    """Report a public GitHub Release mismatch."""


class GitHubClient:
    """Read bounded GitHub REST resources with bearer authentication."""

    def __init__(self, repository: str, token: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
            raise ReleaseVerificationError("invalid GitHub repository")
        if not token or any(
            ord(character) < 0x21 or ord(character) > 0x7E for character in token
        ):
            raise ReleaseVerificationError("invalid GitHub token")
        self._repository = repository
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "justdocs-release-verifier",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def read(self, endpoint: str) -> object:
        """Return one bounded JSON response."""

        url = f"https://api.github.com/repos/{self._repository}/{endpoint}"
        request = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError) as error:
            raise ReleaseVerificationError(f"GitHub query failed: {url}") from error
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ReleaseVerificationError("GitHub response exceeds 2 MiB")
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleaseVerificationError("GitHub response is invalid JSON") from error


def _expect_dict(value: object, label: str) -> dict[str, object]:
    """Return a JSON object or raise a typed mismatch."""

    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"invalid {label} response")
    return value


def _commit_sha(client: GitHubClient, tag: str) -> str:
    """Resolve a lightweight or annotated tag to one commit SHA."""

    encoded = urllib.parse.quote(tag, safe="")
    reference = _expect_dict(client.read(f"git/ref/tags/{encoded}"), "tag ref")
    current = _expect_dict(reference.get("object"), "tag object")
    for _ in range(8):
        kind = current.get("type")
        sha = current.get("sha")
        if not isinstance(sha, str) or SHA.fullmatch(sha) is None:
            raise ReleaseVerificationError("invalid tag object SHA")
        if kind == "commit":
            return sha
        if kind != "tag":
            raise ReleaseVerificationError("tag does not resolve to a commit")
        current = _expect_dict(client.read(f"git/tags/{sha}"), "annotated tag").get(
            "object"
        )
        current = _expect_dict(current, "annotated tag object")
    raise ReleaseVerificationError("annotated tag chain exceeds eight objects")


def _local_assets(directory: Path) -> dict[str, tuple[int, str]]:
    """Return exact local release asset sizes and SHA-256 digests."""

    if not directory.is_dir() or directory.is_symlink():
        raise ReleaseVerificationError("invalid local artifact directory")
    assets: dict[str, tuple[int, str]] = {}
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink():
            raise ReleaseVerificationError(f"invalid local artifact: {path.name}")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        assets[path.name] = (size, f"sha256:{digest.hexdigest()}")
    if not assets:
        raise ReleaseVerificationError("local artifact directory is empty")
    return assets


def _remote_assets(release: dict[str, object]) -> dict[str, tuple[int, str]]:
    """Return exact remote release asset sizes and SHA-256 digests."""

    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise ReleaseVerificationError("invalid GitHub release assets")
    assets: dict[str, tuple[int, str]] = {}
    for value in raw_assets:
        asset = _expect_dict(value, "GitHub release asset")
        name = asset.get("name")
        size = asset.get("size")
        digest = asset.get("digest")
        state = asset.get("state")
        if (
            not isinstance(name, str)
            or not name
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            or state != "uploaded"
            or name in assets
        ):
            raise ReleaseVerificationError("invalid GitHub release asset metadata")
        assets[name] = (size, digest)
    return assets


def _boolean(value: str) -> bool:
    """Parse an exact lowercase Boolean."""

    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _verify(arguments: argparse.Namespace) -> None:
    """Verify release identity, notes, latest binding, and asset digests."""

    if SHA.fullmatch(arguments.target_sha) is None:
        raise ReleaseVerificationError("invalid target commit SHA")
    client = GitHubClient(arguments.repository, os.environ.get("GH_TOKEN", ""))
    if _commit_sha(client, arguments.tag) != arguments.target_sha:
        raise ReleaseVerificationError("release tag target mismatch")
    encoded = urllib.parse.quote(arguments.tag, safe="")
    release = _expect_dict(client.read(f"releases/tags/{encoded}"), "release")
    expected_notes = arguments.notes_file.read_text(encoding="utf-8")
    if (
        release.get("tag_name") != arguments.tag
        or release.get("name") != arguments.release_name
        or release.get("body") != expected_notes
        or release.get("draft") is not False
        or release.get("prerelease") is not arguments.prerelease
        or release.get("immutable") is not False
    ):
        raise ReleaseVerificationError("GitHub release metadata mismatch")
    if not arguments.prerelease:
        latest = _expect_dict(client.read("releases/latest"), "latest release")
        if latest.get("id") != release.get("id"):
            raise ReleaseVerificationError("stable GitHub release is not latest")
    local = _local_assets(arguments.artifacts_dir)
    remote = _remote_assets(release)
    if local != remote:
        raise ReleaseVerificationError("GitHub release asset inventory mismatch")


def _parser() -> argparse.ArgumentParser:
    """Build the public release verification argument parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--release-name", required=True)
    parser.add_argument("--prerelease", required=True, type=_boolean)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--notes-file", required=True, type=Path)
    return parser


def main() -> int:
    """Run public release verification and return a process exit code."""

    try:
        _verify(_parser().parse_args())
    except (OSError, ReleaseVerificationError) as error:
        print(f"GitHub release verification failed: {error}", file=sys.stderr)
        return 1
    print("GitHub release metadata and asset digests verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
