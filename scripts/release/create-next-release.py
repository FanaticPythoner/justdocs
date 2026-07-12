#!/usr/bin/env python3
"""Create a version commit, persistent changelog entry, and annotated release tag."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

PROJECT_FILE = Path("pyproject.toml")
CHANGELOG_FILE = Path("CHANGELOG.md")
CHANGELOG_HEADER = "# justdocs Changelog"
UNRELEASED_HEADING = "## Unreleased"
VERSION_TAG = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
PROJECT_SECTION = re.compile(
    r"(?ms)^(\[project\]\n(?:(?!^\[).)*?^version\s*=\s*)\"([^\"]+)\""
)
SHA = re.compile(r"^[0-9a-f]{40}$")


class ReleasePreparationError(RuntimeError):
    """Report a release preparation invariant failure."""


@dataclass(frozen=True)
class Commit:
    """Store one changelog commit record."""

    sha: str
    short_sha: str
    subject: str
    body: str


def _git(*arguments: str) -> str:
    """Run Git and return stripped standard output."""

    try:
        completed = subprocess.run(
            ("git", *arguments),
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as error:
        raise ReleasePreparationError("Git executable not found") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip()
        message = f"git {' '.join(arguments)} failed with exit code {error.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise ReleasePreparationError(message) from error
    return completed.stdout.strip()


def _project_version(source: str) -> Version:
    """Return the stable three-component project version."""

    match = PROJECT_SECTION.search(source)
    if match is None:
        raise ReleasePreparationError("pyproject.toml project version is missing")
    raw = match.group(2)
    try:
        version = Version(raw)
    except InvalidVersion as error:
        raise ReleasePreparationError(
            f"pyproject.toml project version '{raw}' is invalid"
        ) from error
    if (
        len(version.release) != 3
        or version.epoch
        or version.pre is not None
        or version.post is not None
        or version.dev is not None
        or version.local is not None
    ):
        raise ReleasePreparationError(
            f"pyproject.toml project version '{raw}' is not stable X.Y.Z"
        )
    return version


def _stable_tags() -> tuple[tuple[Version, str], ...]:
    """Return stable release tags ordered from newest to oldest."""

    tags: list[tuple[Version, str]] = []
    for tag in _git("tag", "--list", "v*").splitlines():
        match = VERSION_TAG.fullmatch(tag)
        if match is None:
            continue
        tags.append((Version(".".join(match.groups())), tag))
    return tuple(sorted(tags, reverse=True))


def _increment(version: Version, bump: str) -> Version:
    """Return the requested SemVer increment."""

    major, minor, patch = version.release
    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ReleasePreparationError(f"unsupported release bump '{bump}'")
    return Version(f"{major}.{minor}.{patch}")


def _default_branch(remote: str) -> str:
    """Return the local symbolic default branch for a remote."""

    reference = _git("symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    prefix = f"{remote}/"
    if not reference.startswith(prefix) or reference == prefix:
        raise ReleasePreparationError(
            f"remote '{remote}' default branch reference is invalid"
        )
    return reference.removeprefix(prefix)


def _repository_url(remote: str) -> str:
    """Return the HTTPS repository URL derived from Git remote metadata."""

    override = os.environ.get("RELEASE_REPOSITORY_URL", "").rstrip("/")
    if override:
        if not override.startswith("https://"):
            raise ReleasePreparationError("RELEASE_REPOSITORY_URL must use HTTPS")
        return override
    value = _git("remote", "get-url", remote)
    if value.startswith(("https://", "http://")):
        return value.removesuffix(".git").rstrip("/")
    scp = re.fullmatch(r"git@([^:]+):(.+)", value)
    if scp is not None:
        return f"https://{scp.group(1)}/{scp.group(2).removesuffix('.git')}"
    ssh = re.fullmatch(r"ssh://git@([^/]+)/(.+)", value)
    if ssh is not None:
        return f"https://{ssh.group(1)}/{ssh.group(2).removesuffix('.git')}"
    raise ReleasePreparationError(f"remote '{remote}' URL is unsupported")


def _commits(base: str | None, target: str) -> tuple[Commit, ...]:
    """Return chronological NUL-delimited commit records for one release boundary."""

    revision = f"{base}..{target}" if base else target
    output = subprocess.run(
        (
            "git",
            "log",
            "--reverse",
            "-z",
            "--format=%H%x1f%h%x1f%s%x1f%b",
            revision,
        ),
        check=True,
        capture_output=True,
    ).stdout
    records: list[Commit] = []
    for raw in output.split(b"\0"):
        raw = raw.lstrip(b"\n")
        if not raw:
            continue
        try:
            sha, short_sha, subject, body = raw.decode("utf-8").split("\x1f", 3)
        except (UnicodeDecodeError, ValueError) as error:
            raise ReleasePreparationError("Git commit record is invalid") from error
        if SHA.fullmatch(sha) is None or not short_sha or not subject:
            raise ReleasePreparationError("Git commit record is invalid")
        records.append(Commit(sha, short_sha, subject, body.rstrip()))
    return tuple(records)


def _unreleased_body(source: str) -> tuple[str, str]:
    """Return the Unreleased body and all prior version sections."""

    if not source.startswith(f"{CHANGELOG_HEADER}\n"):
        raise ReleasePreparationError("CHANGELOG.md header is invalid")
    marker = f"\n{UNRELEASED_HEADING}\n"
    start = source.find(marker)
    if start < 0:
        raise ReleasePreparationError("CHANGELOG.md Unreleased section is missing")
    body_start = start + len(marker)
    next_section = source.find("\n## ", body_start)
    if next_section < 0:
        return source[body_start:].strip(), ""
    return source[body_start:next_section].strip(), source[next_section + 1 :].strip()


def _render_entry(
    version: Version,
    release_date: dt.date,
    previous_tag: str | None,
    repository_url: str,
    unreleased: str,
    commits: tuple[Commit, ...],
) -> str:
    """Render one persistent stable-release changelog entry."""

    tag = f"v{version}"
    lines = [
        f"## {tag} - {release_date.isoformat()}",
        "",
        f"- release tag: `{tag}`",
        f"- previous release: `{previous_tag}`"
        if previous_tag
        else "- previous release: none",
    ]
    if unreleased:
        lines.extend(("", unreleased))
    lines.extend(("", "### Included commits", ""))
    if not commits:
        lines.append("- No commits beyond the previous release boundary.")
    for commit in commits:
        lines.append(
            f"- [`{commit.short_sha}`]({repository_url}/commit/{commit.sha}) "
            f"{commit.subject}"
        )
        if commit.body:
            lines.extend(f"  > {line}" for line in commit.body.splitlines())
    return "\n".join(lines).rstrip()


def _atomic_write(path: Path, content: str) -> None:
    """Replace a regular file atomically and durably."""

    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        mode = 0o644
    else:
        if not path.is_file() or path.is_symlink():
            raise ReleasePreparationError(f"release metadata path is unsafe: {path}")
        mode = metadata.st_mode & 0o777
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _replace_version(source: str, version: Version) -> str:
    """Replace the single project version assignment."""

    replaced, count = PROJECT_SECTION.subn(
        lambda match: f'{match.group(1)}"{version}"',
        source,
        count=1,
    )
    if count != 1:
        raise ReleasePreparationError("pyproject.toml project version is ambiguous")
    return replaced


def _release_date(value: str | None) -> dt.date:
    """Return an explicit date or the current UTC date."""

    if value is None:
        return dt.datetime.now(dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ReleasePreparationError(
            f"release date '{value}' is not YYYY-MM-DD"
        ) from error


def _prepare(arguments: argparse.Namespace) -> str:
    """Create release metadata, commit, tag, notes, and optional atomic push."""

    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleasePreparationError("working tree must be clean")
    _git("fetch", "--prune", "--tags", arguments.remote)
    branch = _default_branch(arguments.remote)
    if _git("branch", "--show-current") != branch:
        raise ReleasePreparationError(f"release branch must be '{branch}'")
    head = _git("rev-parse", "--verify", "HEAD^{commit}")
    remote_head = _git(
        "rev-parse",
        "--verify",
        f"refs/remotes/{arguments.remote}/{branch}^{{commit}}",
    )
    if head != remote_head:
        raise ReleasePreparationError(
            f"local '{branch}' must equal '{arguments.remote}/{branch}'"
        )

    project_source = PROJECT_FILE.read_text(encoding="utf-8")
    current = _project_version(project_source)
    tags = _stable_tags()
    if tags:
        previous_version, previous_tag = tags[0]
        if current != previous_version:
            raise ReleasePreparationError(
                f"project version '{current}' does not match latest tag '{previous_tag}'"
            )
        version = _increment(current, arguments.bump)
    else:
        previous_tag = None
        version = current
    tag = f"v{version}"
    if _git("tag", "--list", tag):
        raise ReleasePreparationError(f"tag '{tag}' already exists")

    changelog_source = CHANGELOG_FILE.read_text(encoding="utf-8")
    unreleased, prior_entries = _unreleased_body(changelog_source)
    if re.search(rf"(?m)^## {re.escape(tag)}(?:\s|$)", changelog_source):
        raise ReleasePreparationError(f"CHANGELOG.md already contains '{tag}'")
    commits = _commits(previous_tag, head)
    entry = _render_entry(
        version,
        _release_date(arguments.release_date),
        previous_tag,
        _repository_url(arguments.remote),
        unreleased,
        commits,
    )
    intro = changelog_source.split(f"\n{UNRELEASED_HEADING}\n", 1)[0].rstrip()
    changelog = f"{intro}\n\n{UNRELEASED_HEADING}\n\n{entry}\n"
    if prior_entries:
        changelog = f"{changelog}\n{prior_entries}\n"

    _atomic_write(PROJECT_FILE, _replace_version(project_source, version))
    _atomic_write(CHANGELOG_FILE, changelog)
    _git("add", "--", str(PROJECT_FILE), str(CHANGELOG_FILE))
    _git("commit", "-m", f"release: {tag}")
    _git("tag", "-a", tag, "-m", f"Release {tag}")

    notes = Path("artifacts/release-notes") / f"{tag}.md"
    subprocess.run(
        (
            "bash",
            str(Path(__file__).with_name("write-release-notes.sh")),
            "--channel",
            "stable",
            "--tag",
            tag,
            "--target",
            tag,
            "--output",
            str(notes),
        ),
        check=True,
    )
    if arguments.push:
        _git(
            "push",
            "--atomic",
            arguments.remote,
            f"HEAD:refs/heads/{branch}",
            f"refs/tags/{tag}:refs/tags/{tag}",
        )
    return tag


def _parser() -> argparse.ArgumentParser:
    """Build the release preparation argument parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--release-date")
    parser.add_argument("--push", action="store_true")
    return parser


def main() -> int:
    """Run release preparation and return a process exit code."""

    try:
        tag = _prepare(_parser().parse_args())
    except (OSError, ReleasePreparationError, subprocess.CalledProcessError) as error:
        print(f"release preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"created release commit and annotated tag {tag}")
    print(f"release notes: artifacts/release-notes/{tag}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
