#!/usr/bin/env python3
"""Admit release revisions before reading metadata or exporting build inputs."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
MAX_PROJECT_BYTES = 1024 * 1024


class ReleaseSourceError(RuntimeError):
    """Report an invalid release identity, source boundary, or Git operation."""


def _git(*arguments: str) -> str:
    """Return Git output or raise an explicit command failure."""

    try:
        result = subprocess.run(
            ("git", *arguments),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, UnicodeError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise ReleaseSourceError(f"git {arguments[0]} failed: {detail}") from error
    return result.stdout.strip()


def _required(name: str) -> str:
    """Return a nonempty environment value without line delimiters."""

    value = os.environ.get(name, "")
    if not value or any(character in value for character in "\r\n\0"):
        raise ReleaseSourceError(f"invalid {name}")
    return value


def _sha(value: str) -> str:
    """Return an exact lowercase commit identity."""

    if SHA.fullmatch(value) is None:
        raise ReleaseSourceError("source revision must be a full lowercase commit SHA")
    return value


def _control_identity() -> tuple[str, str]:
    """Bind the control checkout to the event commit and default branch."""

    branch = _required("DEFAULT_BRANCH")
    _git("check-ref-format", f"refs/heads/{branch}")
    event_sha = _sha(_required("EVENT_SHA"))
    if _git("rev-parse", "--verify", "HEAD^{commit}") != event_sha:
        raise ReleaseSourceError("control checkout does not match the event commit")
    return branch, event_sha


def _default_head(branch: str) -> str:
    """Fetch and resolve the repository default branch."""

    reference = f"refs/remotes/origin/{branch}"
    _git("fetch", "--no-tags", "origin", f"refs/heads/{branch}:{reference}")
    return _sha(_git("rev-parse", "--verify", f"{reference}^{{commit}}"))


def _admit(sha: str, default_head: str) -> None:
    """Require a commit reachable from the fetched default branch."""

    _sha(sha)
    if _git("rev-parse", "--verify", f"{sha}^{{commit}}") != sha:
        raise ReleaseSourceError(
            "source identity does not resolve to the admitted commit"
        )
    _git("merge-base", "--is-ancestor", sha, default_head)


def _epoch(sha: str) -> str:
    """Return the admitted commit timestamp in Unix seconds."""

    value = _git("show", "-s", "--format=%ct", sha)
    if re.fullmatch(r"[0-9]+", value) is None:
        raise ReleaseSourceError("invalid source commit timestamp")
    return value


def _branch_event(branch: str) -> None:
    """Require the selected workflow ref to be the default branch."""

    if _required("REF_TYPE") != "branch" or _required("REF_NAME") != branch:
        raise ReleaseSourceError("workflow execution requires the default branch ref")


def _release() -> dict[str, str]:
    """Resolve a version tag with target metadata treated as data."""

    from packaging.version import InvalidVersion, Version

    branch, event_sha = _control_identity()
    event = _required("EVENT_NAME")
    if event == "workflow_dispatch":
        _branch_event(branch)
        tag = _required("INPUT_TAG")
    elif event == "push":
        if _required("REF_TYPE") != "tag":
            raise ReleaseSourceError("release push requires a tag ref")
        tag = _required("REF_NAME")
    else:
        raise ReleaseSourceError(f"unsupported release event: {event}")
    if not tag.startswith("v"):
        raise ReleaseSourceError("release tag must use a v-prefixed package version")
    try:
        version = Version(tag[1:])
    except InvalidVersion as error:
        raise ReleaseSourceError("invalid release tag version") from error
    if version.epoch or version.local is not None or tag != f"v{version}":
        raise ReleaseSourceError(
            "release tag must use a canonical public package version"
        )
    _git("check-ref-format", f"refs/tags/{tag}")
    default_head = _default_head(branch)
    reference = f"refs/tags/{tag}"
    _git("fetch", "--no-tags", "origin", f"{reference}:{reference}")
    sha = _sha(_git("rev-parse", "--verify", f"{reference}^{{commit}}"))
    _admit(sha, default_head)
    if event == "push" and sha != event_sha:
        raise ReleaseSourceError("release tag does not match the push commit")
    blob = f"{sha}:pyproject.toml"
    size = _git("cat-file", "-s", blob)
    if not size.isdecimal() or not 0 < int(size) <= MAX_PROJECT_BYTES:
        raise ReleaseSourceError("release project metadata exceeds 1 MiB or is empty")
    try:
        project = tomllib.loads(_git("show", blob))["project"]
        raw_version = project["version"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise ReleaseSourceError("invalid release project metadata") from error
    if not isinstance(raw_version, str) or tag != f"v{raw_version}":
        raise ReleaseSourceError("release tag does not match target package version")
    return {
        "tag": tag,
        "prerelease": str(version.is_prerelease).lower(),
        "release_ref": sha,
        "release_sha": sha,
        "source_date_epoch": _epoch(sha),
    }


def _latest() -> dict[str, str]:
    """Resolve the default branch without selecting another control revision."""

    branch, event_sha = _control_identity()
    if _required("EVENT_NAME") not in {"push", "schedule", "workflow_dispatch"}:
        raise ReleaseSourceError("unsupported latest release event")
    _branch_event(branch)
    sha = _default_head(branch)
    if sha != event_sha:
        raise ReleaseSourceError("latest source changed after the triggering event")
    return {
        "release_ref": sha,
        "release_sha": sha,
        "release_short_sha": sha[:12],
        "source_date_epoch": _epoch(sha),
    }


def _export(reference: str, directory: Path) -> dict[str, str]:
    """Export an admitted commit into a new confined build directory."""

    sha = _sha(reference)
    branch, _ = _control_identity()
    default_head = _default_head(branch)
    _git("fetch", "--no-tags", "origin", sha)
    _admit(sha, default_head)
    epoch = _epoch(sha)
    root = Path.cwd().resolve()
    destination = directory.absolute()
    if (
        destination == root
        or not destination.is_relative_to(root)
        or destination.resolve() != destination
        or destination.exists()
    ):
        raise ReleaseSourceError(
            "source directory must be a new confined workspace path"
        )
    with tempfile.TemporaryDirectory(dir=root, prefix=".release-source-") as temporary:
        stage = Path(temporary)
        archive = stage / "source.tar"
        _git("archive", "--format=tar", f"--output={archive}", sha)
        unpacked = stage / "source"
        unpacked.mkdir()
        try:
            with tarfile.open(archive, "r:") as stream:
                stream.extractall(unpacked, filter="data")
        except (tarfile.TarError, OSError) as error:
            raise ReleaseSourceError("invalid release source archive") from error
        unpacked.rename(destination)
    return {"source_date_epoch": epoch}


def main() -> int:
    """Emit admitted source metadata or return an explicit failure."""

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resolve")
    commands.add_parser("latest")
    export = commands.add_parser("export")
    export.add_argument("--ref", required=True)
    export.add_argument("--directory", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "resolve":
            values = _release()
        elif arguments.command == "latest":
            values = _latest()
        else:
            values = _export(arguments.ref, arguments.directory)
        output = "".join(f"{key}={value}\n" for key, value in values.items())
        output_file = os.environ.get("GITHUB_OUTPUT")
        if output_file:
            with Path(output_file).open("a", encoding="utf-8") as stream:
                stream.write(output)
        else:
            print(output, end="")
    except (OSError, ReleaseSourceError) as error:
        print(f"release source rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
