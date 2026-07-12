#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, NoReturn
from urllib.parse import quote, urlencode

try:
    from secure_posix_paths import (
        BoundCreatedDirectory,
        SecurePathError,
        bind_created_directory as secure_bind_created_directory,
        canonical_child as secure_canonical_child,
        canonical_directory as secure_canonical_directory,
        directory_open_flags,
        open_bound_created_directory as secure_open_bound_created_directory,
        open_absolute_directory as secure_open_absolute_directory,
        verify_bound_created_directory as secure_verify_bound_created_directory,
    )
except ModuleNotFoundError as import_error:
    if import_error.name != "secure_posix_paths":
        raise
    from scripts.release.secure_posix_paths import (
        BoundCreatedDirectory,
        SecurePathError,
        bind_created_directory as secure_bind_created_directory,
        canonical_child as secure_canonical_child,
        canonical_directory as secure_canonical_directory,
        directory_open_flags,
        open_bound_created_directory as secure_open_bound_created_directory,
        open_absolute_directory as secure_open_absolute_directory,
        verify_bound_created_directory as secure_verify_bound_created_directory,
    )


SNAPSHOT_SCRIPT = Path(__file__).with_name("stage-release-inputs.py")
VALIDATION_SCRIPT = Path(__file__).with_name("github-repository.sh")
TRANSACTION_PREFIX = "justdocs-release-transaction-"
TRANSACTION_METADATA = "transaction.json"
TRANSACTION_VERSION = 6
HASH_BUFFER_SIZE = 1024 * 1024
RELEASE_QUERY = """query($owner: String!, $name: String!, $tag: String!) {
  repository(owner: $owner, name: $name) {
    release(tagName: $tag) {
      databaseId
      immutable
      isDraft
      isLatest
      isPrerelease
      tagName
      name
      description
    }
  }
}"""
TAG_QUERY = """query($owner: String!, $name: String!, $ref: String!) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $ref) {
      target {
        oid
      }
    }
  }
}"""
ASSET_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
TRANSACTION_UPLOAD_ASSET = re.compile(r"justdocs-upload-[0-9a-f]{32}")
LEGACY_DETACHED_TAG = re.compile(r"untagged-[0-9a-f]{20}")
LEGACY_RELEASE_NAME = re.compile(r"Latest Nightly Build \(([0-9a-f]{12})\)")
LEGACY_MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)")
LEGACY_WHEEL_NAME = re.compile(
    r"justdocs-([0-9A-Za-z][0-9A-Za-z._]*)-py3-none-any\.whl"
)
LEGACY_MANIFEST_LIMIT = 64 * 1024
LEGACY_REPOSITORY = "FanaticPythoner/justdocs"
LEGACY_TAG = "latest"
CURL_VERSION = re.compile(r"curl ([0-9]+)\.([0-9]+)\.([0-9]+)(?:[.-][^ ]+)?(?: |$)")
MINIMUM_CURL_VERSION = (7, 76, 0)
API_VERSION = "2026-03-10"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
TERMINAL_PHASES = {
    "preflight",
    "prepared",
    "committed",
    "rolled_back",
    "rolled_back_with_tag",
}


class ReleaseTransactionError(RuntimeError):
    pass


class ReleaseTransactionInterrupted(ReleaseTransactionError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    database_id: int
    name: str
    label: str
    content_type: str
    size: int
    digest: str | None
    state: str


@dataclass(frozen=True)
class ReleaseState:
    database_id: int
    tag_name: str
    immutable: bool
    is_draft: bool
    is_latest: bool
    is_prerelease: bool
    name: str
    description: str
    assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True)
class TransactionMetadata:
    transaction_name: str
    root_device: int
    root_inode: int
    tag: str
    repository: str
    parent: Path
    create_or_move_tag: bool
    target_sha: str
    original_tag_sha: str | None
    phase: str
    original_release: ReleaseState | None
    prepared_release: ReleaseState | None
    created_release_id: int | None
    precreate_release_ids: tuple[int, ...] | None
    create_attempted: bool
    desired_name: str
    desired_description: str
    desired_prerelease: bool
    desired_asset_digests: tuple[tuple[str, str], ...]
    owned_asset_ids: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class LegacyReleaseState:
    release: ReleaseState
    published_at: str


@dataclass(frozen=True)
class LegacyAssetPlan:
    original: ReleaseAsset
    rollback_name: str
    target_name: str


@dataclass(frozen=True)
class LegacyRecoveryPlan:
    release_id: int
    target_sha: str
    detached_tag: str | None
    name: str
    description: str
    published_at: str
    assets: tuple[LegacyAssetPlan, ...]


def _interrupt(signum: int, _frame: object) -> NoReturn:
    raise ReleaseTransactionInterrupted(f"received signal {signum}")


def _verify_root_identity(
    descriptor: int,
    metadata: TransactionMetadata,
) -> None:
    root_metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_dev != metadata.root_device
        or root_metadata.st_ino != metadata.root_inode
    ):
        raise ReleaseTransactionError("transaction root identity changed")


@contextmanager
def _open_transaction_directory(
    root: Path,
    metadata: TransactionMetadata,
) -> Iterator[int]:
    with _open_bound_directory(root) as root_descriptor:
        _verify_root_identity(root_descriptor, metadata)
        yield root_descriptor


@contextmanager
def _transaction_lock(
    root: Path,
    metadata: TransactionMetadata,
) -> Iterator[None]:
    with _open_transaction_directory(root, metadata) as root_descriptor:
        descriptor = os.open(
            ".transaction.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_descriptor,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ReleaseTransactionError("invalid transaction lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _run(arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as error:
        raise ReleaseTransactionError(
            f"required executable not found: {arguments[0]}"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        message = f"command failed with exit code {error.returncode}: {arguments[0]}"
        if detail:
            message = f"{message}: {detail}"
        raise ReleaseTransactionError(message) from error


def _authorization_header() -> bytes:
    token = os.environ.get("GH_TOKEN", "")
    try:
        encoded_token = token.encode("ascii")
    except UnicodeEncodeError as error:
        raise ReleaseTransactionError("invalid GitHub authorization token") from error
    authorization = b"Authorization: Bearer " + encoded_token + b"\n"
    if not encoded_token or any(
        value < 0x21 or value > 0x7E for value in encoded_token
    ):
        raise ReleaseTransactionError("invalid GitHub authorization token")
    return authorization


def _run_curl_with_input(
    arguments: tuple[str, ...],
    source: BinaryIO,
    content_length: int,
) -> subprocess.CompletedProcess[str]:
    if (
        arguments[:2] != ("curl", "--disable")
        or arguments.count("--data-binary") != 1
        or arguments[arguments.index("--data-binary") + 1 :][:1] != ("@-",)
        or any(argument.lower().startswith("content-length:") for argument in arguments)
        or content_length < 0
    ):
        raise ReleaseTransactionError("invalid authenticated curl command")
    authorization = _authorization_header()
    authorization_read, authorization_write = os.pipe()
    try:
        try:
            try:
                pipe_buffer = os.fpathconf(authorization_write, "PC_PIPE_BUF")
            except OSError as error:
                raise ReleaseTransactionError(
                    "GitHub authorization pipe capacity query failed"
                ) from error
            if pipe_buffer <= 0 or len(authorization) > pipe_buffer:
                raise ReleaseTransactionError(
                    "GitHub authorization header is too large"
                )
            if os.write(authorization_write, authorization) != len(authorization):
                raise ReleaseTransactionError("GitHub authorization pipe write failed")
        finally:
            os.close(authorization_write)
        authorization_path = f"/dev/fd/{authorization_read}"
        request_arguments = arguments[:-1] + (
            "-H",
            f"@{authorization_path}",
            "-H",
            f"Content-Length: {content_length}",
            arguments[-1],
        )
        child_environment = dict(os.environ)
        child_environment.pop("GH_TOKEN", None)
        child_environment.pop("GITHUB_TOKEN", None)
        try:
            completed = subprocess.run(
                request_arguments,
                check=True,
                stdin=source,
                text=False,
                capture_output=True,
                env=child_environment,
                pass_fds=(authorization_read,),
            )
        except FileNotFoundError as error:
            raise ReleaseTransactionError(
                "required executable not found: curl"
            ) from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or b"").decode("utf-8", "replace").strip()
            message = f"command failed with exit code {error.returncode}: curl"
            if detail:
                message = f"{message}: {detail}"
            raise ReleaseTransactionError(message) from error
    finally:
        os.close(authorization_read)
    try:
        stdout = completed.stdout.decode("utf-8")
        stderr = completed.stderr.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReleaseTransactionError("invalid command response encoding") from error
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout,
        stderr,
    )


def _run_curl_with_regular_input(
    arguments: tuple[str, ...],
    path: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        descriptor = os.open(path, _required_open_flags())
    except OSError as error:
        raise ReleaseTransactionError(f"invalid transaction input: {path}") from error
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ReleaseTransactionError(f"invalid transaction input: {path}")
        return _run_curl_with_input(arguments, source, metadata.st_size)


def _run_curl_with_bytes_input(
    arguments: tuple[str, ...],
    payload: bytes,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryFile() as source:
        source.write(payload)
        source.seek(0)
        return _run_curl_with_input(arguments, source, len(payload))


def _validate_authorization_fd_path() -> None:
    read_descriptor, write_descriptor = os.pipe()
    duplicate_descriptor: int | None = None
    try:
        if os.write(write_descriptor, b"x") != 1:
            raise ReleaseTransactionError("authorization descriptor probe failed")
        os.close(write_descriptor)
        write_descriptor = -1
        duplicate_descriptor = os.open(
            f"/dev/fd/{read_descriptor}",
            os.O_RDONLY,
        )
        if os.read(duplicate_descriptor, 1) != b"x":
            raise ReleaseTransactionError("authorization descriptor probe failed")
    except OSError as error:
        raise ReleaseTransactionError(
            "GitHub release uploads require readable /dev/fd descriptors"
        ) from error
    finally:
        if duplicate_descriptor is not None:
            os.close(duplicate_descriptor)
        if write_descriptor >= 0:
            os.close(write_descriptor)
        os.close(read_descriptor)


def _validate_upload_transport() -> None:
    first_line = _run(("curl", "--disable", "--version")).stdout.splitlines()[:1]
    match = CURL_VERSION.match(first_line[0]) if first_line else None
    if match is None:
        raise ReleaseTransactionError("invalid curl version response")
    version = tuple(int(component) for component in match.groups())
    if version < MINIMUM_CURL_VERSION:
        encoded = ".".join(str(component) for component in MINIMUM_CURL_VERSION)
        raise ReleaseTransactionError(f"curl {encoded} or newer is required")
    _validate_authorization_fd_path()


def _validate_preflight_inputs(tag: str, create_or_move_tag: str) -> str:
    completed = _run(
        (
            "bash",
            "-c",
            'source "$1"; release_validate_tag "$2" || exit; '
            'release_validate_boolean create_or_move_tag "$3" || exit; '
            "release_github_repository",
            "bash",
            str(VALIDATION_SCRIPT),
            tag,
            create_or_move_tag,
        )
    )
    return completed.stdout.strip()


def _validate_publish_inputs(
    tag: str,
    release_name: str,
    prerelease: str,
    purge_existing_assets: str,
) -> str:
    completed = _run(
        (
            "bash",
            "-c",
            'source "$1"; release_validate_tag "$2" || exit; '
            'release_validate_name "$3" || exit; '
            'release_validate_boolean prerelease "$4" || exit; '
            'release_validate_boolean purge_existing_assets "$5" || exit; '
            "release_github_repository",
            "bash",
            str(VALIDATION_SCRIPT),
            tag,
            release_name,
            prerelease,
            purge_existing_assets,
        )
    )
    return completed.stdout.strip()


def _repository_parts(repository: str) -> tuple[str, str]:
    owner, name = repository.split("/", 1)
    return owner, name


def _remote_tag_sha(repository: str, tag: str) -> str | None:
    owner, name = _repository_parts(repository)
    try:
        payload = json.loads(
            _gh(
                "api",
                "graphql",
                "-f",
                f"query={TAG_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-f",
                f"ref=refs/tags/{tag}",
            )
        )
        reference = payload["data"]["repository"]["ref"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseTransactionError("invalid GitHub tag query response") from error
    if reference is None:
        return None
    try:
        target_sha = reference["target"]["oid"]
    except (KeyError, TypeError) as error:
        raise ReleaseTransactionError("invalid GitHub tag query response") from error
    if not isinstance(target_sha, str) or COMMIT_SHA.fullmatch(target_sha) is None:
        raise ReleaseTransactionError("invalid GitHub tag target")
    return target_sha


def _resolve_commit(repository: str, reference: str) -> str:
    try:
        payload = json.loads(
            _gh(
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {API_VERSION}",
                f"repos/{repository}/commits/{quote(reference, safe='')}",
            )
        )
        resolved = payload["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseTransactionError("invalid GitHub commit query response") from error
    if not isinstance(resolved, str) or COMMIT_SHA.fullmatch(resolved) is None:
        raise ReleaseTransactionError("invalid GitHub commit query response")
    return resolved


def _validate_target_sha(raw_sha: str, repository: str) -> str:
    if COMMIT_SHA.fullmatch(raw_sha) is None:
        raise ReleaseTransactionError("invalid release target SHA")
    if _resolve_commit(repository, raw_sha) != raw_sha:
        raise ReleaseTransactionError("release target is not a GitHub commit")
    return raw_sha


def _validate_monotonic_tag(
    repository: str,
    tag: str,
    current_tag_sha: str | None,
    target_sha: str,
) -> None:
    if tag != "latest" or current_tag_sha is None:
        return
    current_commit = _resolve_commit(repository, tag)
    endpoint = (
        f"repos/{repository}/compare/{quote(current_commit, safe='')}"
        f"...{quote(target_sha, safe='')}"
    )
    try:
        payload = json.loads(
            _gh(
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {API_VERSION}",
                endpoint,
            )
        )
        comparison = payload["status"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseTransactionError(
            "invalid GitHub commit comparison response"
        ) from error
    if comparison not in {"ahead", "identical"}:
        raise ReleaseTransactionError("latest release target is not monotonic")


def _set_remote_tag(
    repository: str,
    tag: str,
    target_sha: str,
    expected_current_sha: str | None,
) -> None:
    current_sha = _remote_tag_sha(repository, tag)
    if current_sha != expected_current_sha:
        raise ReleaseTransactionError("remote release tag ownership changed")
    endpoint = f"repos/{repository}/git/refs/tags/{quote(tag, safe='')}"
    if current_sha is None:
        _gh(
            "api",
            "-X",
            "POST",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
            f"repos/{repository}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={target_sha}",
        )
    elif current_sha != target_sha:
        _gh(
            "api",
            "-X",
            "PATCH",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
            endpoint,
            "-f",
            f"sha={target_sha}",
            "-F",
            "force=false",
        )
    if _remote_tag_sha(repository, tag) != target_sha:
        raise ReleaseTransactionError("remote release tag verification failed")


def _gh(*arguments: str) -> str:
    return _run(("gh", *arguments)).stdout


def _gh_optional_not_found(*arguments: str) -> str | None:
    command = ("gh", *arguments)
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as error:
        raise ReleaseTransactionError("required executable not found: gh") from error
    if completed.returncode == 0:
        return completed.stdout
    detail = completed.stderr.strip()
    if completed.returncode == 1 and detail.endswith("(HTTP 404)"):
        return None
    message = f"command failed with exit code {completed.returncode}: gh"
    if detail:
        message = f"{message}: {detail}"
    raise ReleaseTransactionError(message)


def _expect_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ReleaseTransactionError(f"invalid GitHub release field: {field}")
    return value


def _expect_string_or_empty(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ReleaseTransactionError(f"invalid GitHub release field: {field}")
    return value


def _expect_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseTransactionError(f"invalid GitHub release field: {field}")
    return value


def _parse_asset(value: object) -> ReleaseAsset:
    if not isinstance(value, dict):
        raise ReleaseTransactionError("invalid GitHub release asset shape")
    database_id = value.get("id")
    name = value.get("name")
    label = value.get("label")
    content_type = value.get("content_type")
    size = value.get("size")
    digest = value.get("digest")
    asset_state = value.get("state")
    uploaded = asset_state == "uploaded"
    starter = asset_state == "starter"
    if (
        type(database_id) is not int
        or database_id <= 0
        or not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "#" in name
        or "\x00" in name
        or (label is not None and not isinstance(label, str))
        or not isinstance(content_type, str)
        or uploaded
        and not content_type
        or type(size) is not int
        or size < 0
        or not (uploaded or starter)
        or uploaded
        and (not isinstance(digest, str) or ASSET_DIGEST.fullmatch(digest) is None)
        or starter
        and (digest is not None or size != 0)
    ):
        raise ReleaseTransactionError("invalid GitHub release asset value")
    return ReleaseAsset(
        database_id=database_id,
        name=name,
        label=label or "",
        content_type=content_type,
        size=size,
        digest=digest,
        state=asset_state,
    )


def _query_release_metadata_by_tag(
    repository: str,
    tag: str,
) -> ReleaseState | None:
    owner, name = _repository_parts(repository)
    try:
        payload = json.loads(
            _gh(
                "api",
                "graphql",
                "-f",
                f"query={RELEASE_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-f",
                f"tag={tag}",
            )
        )
        release = payload["data"]["repository"]["release"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseTransactionError(
            "invalid GitHub release query response"
        ) from error
    if release is None:
        return None
    if not isinstance(release, dict):
        raise ReleaseTransactionError("invalid GitHub release query response")
    database_id = release.get("databaseId")
    if type(database_id) is not int or database_id <= 0:
        raise ReleaseTransactionError("invalid GitHub release field: databaseId")
    return ReleaseState(
        database_id=database_id,
        tag_name=_expect_nonempty_string(release.get("tagName"), "tagName"),
        immutable=_expect_bool(release.get("immutable"), "immutable"),
        is_draft=_expect_bool(release.get("isDraft"), "isDraft"),
        is_latest=_expect_bool(release.get("isLatest"), "isLatest"),
        is_prerelease=_expect_bool(release.get("isPrerelease"), "isPrerelease"),
        name=_expect_string_or_empty(release.get("name"), "name"),
        description=_expect_string_or_empty(release.get("description"), "description"),
        assets=(),
    )


def _parse_rest_release_metadata(value: object) -> ReleaseState:
    if not isinstance(value, dict):
        raise ReleaseTransactionError("invalid GitHub release response")
    database_id = value.get("id")
    if type(database_id) is not int or database_id <= 0:
        raise ReleaseTransactionError("invalid GitHub release field: id")
    return ReleaseState(
        database_id=database_id,
        tag_name=_expect_nonempty_string(value.get("tag_name"), "tag_name"),
        immutable=_expect_bool(value.get("immutable"), "immutable"),
        is_draft=_expect_bool(value.get("draft"), "draft"),
        is_latest=False,
        is_prerelease=_expect_bool(value.get("prerelease"), "prerelease"),
        name=_expect_string_or_empty(value.get("name"), "name"),
        description=_expect_string_or_empty(value.get("body"), "body"),
        assets=(),
    )


def _parse_rest_release(value: object) -> ReleaseState:
    release = _parse_rest_release_metadata(value)
    raw_assets = value.get("assets") if isinstance(value, dict) else None
    if not isinstance(raw_assets, list):
        raise ReleaseTransactionError("invalid GitHub release response")
    assets = tuple(_parse_asset(asset) for asset in raw_assets)
    if len({asset.name for asset in assets}) != len(assets):
        raise ReleaseTransactionError("duplicate GitHub release asset name")
    return replace(release, assets=tuple(sorted(assets, key=lambda asset: asset.name)))


def _query_release_document_by_id(
    repository: str,
    release_id: int,
) -> dict[str, object] | None:
    encoded = _gh_optional_not_found(
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{repository}/releases/{release_id}",
    )
    if encoded is None:
        return None
    try:
        document = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ReleaseTransactionError("invalid GitHub release response") from error
    if not isinstance(document, dict):
        raise ReleaseTransactionError("invalid GitHub release response")
    return document


def _query_release_metadata_by_id(
    repository: str,
    release_id: int,
) -> ReleaseState | None:
    document = _query_release_document_by_id(repository, release_id)
    if document is None:
        return None
    rest_state = _parse_rest_release_metadata(document)
    if rest_state.database_id != release_id:
        raise ReleaseTransactionError("GitHub release identity changed")
    return rest_state


def _query_paginated_items(endpoint: str, entity: str) -> tuple[object, ...]:
    try:
        pages = json.loads(
            _gh(
                "api",
                "--paginate",
                "--slurp",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {API_VERSION}",
                endpoint,
            )
        )
    except json.JSONDecodeError as error:
        raise ReleaseTransactionError(f"invalid GitHub {entity} response") from error
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseTransactionError(f"invalid GitHub {entity} response")
    return tuple(value for page in pages for value in page)


def _query_assets(repository: str, release_id: int) -> tuple[ReleaseAsset, ...]:
    endpoint = f"repos/{repository}/releases/{release_id}/assets?per_page=100"
    assets = tuple(
        _parse_asset(value)
        for value in _query_paginated_items(endpoint, "release asset")
    )
    names = [asset.name for asset in assets]
    if len(names) != len(set(names)):
        raise ReleaseTransactionError("duplicate GitHub release asset name")
    return tuple(sorted(assets, key=lambda asset: asset.name))


def _query_legacy_assets(
    repository: str,
    release_id: int,
) -> tuple[ReleaseAsset, ...]:
    endpoint = f"repos/{repository}/releases/{release_id}/assets?per_page=100"
    values = _query_paginated_items(endpoint, "release asset")
    for value in values:
        uploader = value.get("uploader") if isinstance(value, dict) else None
        if (
            not isinstance(uploader, dict)
            or uploader.get("login") != "github-actions[bot]"
        ):
            raise ReleaseTransactionError("invalid detached latest asset uploader")
    assets = tuple(_parse_asset(value) for value in values)
    names = [asset.name for asset in assets]
    if len(names) != len(set(names)):
        raise ReleaseTransactionError("duplicate GitHub release asset name")
    return tuple(sorted(assets, key=lambda asset: asset.name))


def _query_release_inventory(repository: str) -> tuple[ReleaseState, ...]:
    endpoint = f"repos/{repository}/releases?per_page=100"
    releases = tuple(
        _parse_rest_release_metadata(value)
        for value in _query_paginated_items(endpoint, "release list")
    )
    release_ids = [release.database_id for release in releases]
    if len(release_ids) != len(set(release_ids)):
        raise ReleaseTransactionError("duplicate GitHub release identity")
    return tuple(sorted(releases, key=lambda release: release.database_id))


def _query_release_by_tag(repository: str, tag: str) -> ReleaseState | None:
    before = _query_release_metadata_by_tag(repository, tag)
    if before is None:
        return None
    assets = _query_assets(repository, before.database_id)
    after = _query_release_metadata_by_tag(repository, tag)
    if after is None or replace(before, is_latest=after.is_latest) != after:
        raise ReleaseTransactionError("GitHub release changed during query")
    return replace(after, assets=assets)


def _query_release_by_id(
    repository: str,
    release_id: int,
) -> ReleaseState | None:
    before = _query_release_metadata_by_id(repository, release_id)
    if before is None:
        return None
    assets = _query_assets(repository, release_id)
    after = _query_release_metadata_by_id(repository, release_id)
    if after != before:
        raise ReleaseTransactionError("GitHub release changed during ID query")
    return replace(before, assets=assets)


def _query_legacy_release_by_id(
    repository: str,
    release_id: int,
) -> LegacyReleaseState | None:
    before_document = _query_release_document_by_id(repository, release_id)
    if before_document is None:
        return None
    before = _parse_rest_release_metadata(before_document)
    before_author = before_document.get("author")
    if (
        not isinstance(before_author, dict)
        or before_author.get("login") != "github-actions[bot]"
    ):
        raise ReleaseTransactionError("invalid detached latest release author")
    before_published_at = _expect_nonempty_string(
        before_document.get("published_at"),
        "published_at",
    )
    assets = _query_legacy_assets(repository, release_id)
    after_document = _query_release_document_by_id(repository, release_id)
    if after_document is None:
        raise ReleaseTransactionError("GitHub release changed during legacy query")
    after = _parse_rest_release_metadata(after_document)
    after_author = after_document.get("author")
    if (
        not isinstance(after_author, dict)
        or after_author.get("login") != "github-actions[bot]"
    ):
        raise ReleaseTransactionError("invalid detached latest release author")
    after_published_at = _expect_nonempty_string(
        after_document.get("published_at"),
        "published_at",
    )
    if (
        before.database_id != release_id
        or after.database_id != release_id
        or before != after
        or before_published_at != after_published_at
    ):
        raise ReleaseTransactionError("GitHub release changed during legacy query")
    return LegacyReleaseState(
        release=replace(before, assets=assets),
        published_at=before_published_at,
    )


def _stream_legacy_asset(
    repository: str,
    asset: ReleaseAsset,
) -> bytes | None:
    command = (
        "gh",
        "api",
        "-H",
        "Accept: application/octet-stream",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{repository}/releases/assets/{asset.database_id}",
    )
    with tempfile.TemporaryFile() as error_output:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=error_output,
            )
        except FileNotFoundError as error:
            raise ReleaseTransactionError(
                "required executable not found: gh"
            ) from error
        digest = hashlib.sha256()
        size = 0
        captured: bytearray | None = bytearray()
        try:
            if process.stdout is None:
                raise ReleaseTransactionError("invalid GitHub asset download pipe")
            while chunk := process.stdout.read(HASH_BUFFER_SIZE):
                digest.update(chunk)
                size += len(chunk)
                if captured is not None:
                    if len(captured) + len(chunk) <= LEGACY_MANIFEST_LIMIT:
                        captured.extend(chunk)
                    else:
                        captured = None
            returncode = process.wait()
        except Exception:
            process.kill()
            process.wait()
            raise
        if returncode != 0:
            error_output.seek(0)
            detail = error_output.read().decode("utf-8", "replace").strip()
            message = f"command failed with exit code {returncode}: gh"
            if detail:
                message = f"{message}: {detail}"
            raise ReleaseTransactionError(message)
    if size != asset.size or f"sha256:{digest.hexdigest()}" != asset.digest:
        raise ReleaseTransactionError(
            f"legacy release asset byte verification failed: {asset.database_id}"
        )
    return bytes(captured) if captured is not None else None


def _parse_legacy_manifest(payload: bytes) -> tuple[tuple[str, str], ...] | None:
    try:
        encoded = payload.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not encoded.endswith("\n") or "\r" in encoded:
        return None
    lines = encoded.removesuffix("\n").split("\n")
    if len(lines) != 4:
        return None
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = LEGACY_MANIFEST_LINE.fullmatch(line)
        if match is None:
            return None
        digest, name = match.groups()
        entries.append((name, f"sha256:{digest}"))
    names = [name for name, _digest in entries]
    digests = [digest for _name, digest in entries]
    if len(set(names)) != 4 or len(set(digests)) != 4:
        return None
    required = {"install.ps1", "install.sh"}
    if not required.issubset(names):
        return None
    wheel_names = [name for name in names if LEGACY_WHEEL_NAME.fullmatch(name)]
    sdist_names = [
        name
        for name in names
        if name.startswith("justdocs-") and name.endswith(".tar.gz")
    ]
    if len(wheel_names) != 1 or len(sdist_names) != 1:
        return None
    wheel_match = LEGACY_WHEEL_NAME.fullmatch(wheel_names[0])
    if wheel_match is None:
        return None
    version = wheel_match.group(1)
    if sdist_names[0] != f"justdocs-{version}.tar.gz" or set(names) != {
        "install.ps1",
        "install.sh",
        wheel_names[0],
        sdist_names[0],
    }:
        return None
    return tuple(entries)


def _legacy_target_sha(name: str, description: str) -> str:
    name_match = LEGACY_RELEASE_NAME.fullmatch(name)
    body_match = re.match(
        r"\A# justdocs latest\n\n"
        r"- branch: `main`\n"
        r"- target commit: \[`([0-9a-f]{40})`\]"
        r"\(https://github\.com/FanaticPythoner/justdocs/commit/\1\)"
        r"(?:\n|\Z)",
        description,
    )
    if (
        name_match is None
        or body_match is None
        or description.count("# justdocs latest") != 1
        or description.count("- branch: `main`") != 1
        or description.count("- target commit:") != 1
        or not body_match.group(1).startswith(name_match.group(1))
    ):
        raise ReleaseTransactionError("invalid detached latest release metadata")
    return body_match.group(1)


def _build_legacy_recovery_plan(
    legacy: LegacyReleaseState,
    expected_tag_sha: str,
    *,
    terminal: bool,
) -> LegacyRecoveryPlan:
    release = legacy.release
    target_sha = _legacy_target_sha(release.name, release.description)
    expected_tag_name = LEGACY_TAG if terminal else None
    if (
        release.immutable
        or release.is_draft == terminal
        or not release.is_prerelease
        or release.is_latest
        or target_sha != expected_tag_sha
        or terminal
        and release.tag_name != expected_tag_name
        or not terminal
        and LEGACY_DETACHED_TAG.fullmatch(release.tag_name) is None
        or len(release.assets) != 5
        or len({asset.database_id for asset in release.assets}) != 5
        or len({asset.digest for asset in release.assets}) != 5
        or any(
            asset.state != "uploaded" or asset.digest is None or asset.label
            for asset in release.assets
        )
    ):
        raise ReleaseTransactionError("invalid detached latest release state")
    captured = {
        asset.database_id: _stream_legacy_asset(LEGACY_REPOSITORY, asset)
        for asset in release.assets
    }
    manifest_candidates: list[tuple[ReleaseAsset, tuple[tuple[str, str], ...]]] = []
    for asset in release.assets:
        payload = captured[asset.database_id]
        if payload is None:
            continue
        entries = _parse_legacy_manifest(payload)
        if entries is None:
            continue
        other_digests = {
            other.digest
            for other in release.assets
            if other.database_id != asset.database_id
        }
        if {digest for _name, digest in entries} == other_digests:
            manifest_candidates.append((asset, entries))
    if len(manifest_candidates) != 1:
        raise ReleaseTransactionError("invalid detached latest release manifest")
    manifest_asset, entries = manifest_candidates[0]
    assets_by_digest = {asset.digest: asset for asset in release.assets}
    target_assets = [
        LegacyAssetPlan(
            original=assets_by_digest[digest],
            rollback_name=f"justdocs-rollback-{assets_by_digest[digest].database_id}",
            target_name=name,
        )
        for name, digest in entries
    ]
    target_assets.sort(key=lambda plan: plan.target_name)
    target_assets.append(
        LegacyAssetPlan(
            original=manifest_asset,
            rollback_name=f"justdocs-rollback-{manifest_asset.database_id}",
            target_name="SHA256SUMS.txt",
        )
    )
    if len({plan.original.database_id for plan in target_assets}) != 5:
        raise ReleaseTransactionError("invalid detached latest release asset mapping")
    plan = LegacyRecoveryPlan(
        release_id=release.database_id,
        target_sha=target_sha,
        detached_tag=None if terminal else release.tag_name,
        name=release.name,
        description=release.description,
        published_at=legacy.published_at,
        assets=tuple(target_assets),
    )
    _legacy_recovery_progress(legacy, plan, terminal=terminal)
    return plan


def _legacy_recovery_progress(
    legacy: LegacyReleaseState,
    plan: LegacyRecoveryPlan,
    *,
    terminal: bool,
) -> int:
    release = legacy.release
    if (
        release.database_id != plan.release_id
        or release.immutable
        or release.is_draft == terminal
        or not release.is_prerelease
        or release.is_latest
        or release.name != plan.name
        or release.description != plan.description
        or not terminal
        and legacy.published_at != plan.published_at
        or terminal
        and release.tag_name != LEGACY_TAG
        or not terminal
        and release.tag_name != plan.detached_tag
    ):
        raise ReleaseTransactionError("detached latest release identity changed")
    current_by_id = {asset.database_id: asset for asset in release.assets}
    if set(current_by_id) != {asset.original.database_id for asset in plan.assets}:
        raise ReleaseTransactionError("detached latest release assets changed")
    renamed: list[bool] = []
    for asset_plan in plan.assets:
        current = current_by_id[asset_plan.original.database_id]
        if current.name not in {asset_plan.rollback_name, asset_plan.target_name}:
            raise ReleaseTransactionError("detached latest release asset name changed")
        if replace(current, name=asset_plan.original.name) != asset_plan.original:
            raise ReleaseTransactionError(
                "detached latest release asset metadata changed"
            )
        renamed.append(current.name == asset_plan.target_name)
    progress = 0
    while progress < len(renamed) and renamed[progress]:
        progress += 1
    if any(renamed[progress:]) or terminal and progress != len(plan.assets):
        raise ReleaseTransactionError("invalid detached latest recovery state")
    return progress


def _stable_legacy_tag_sha(repository: str, tag: str) -> str | None:
    before = _remote_tag_sha(repository, tag)
    after = _remote_tag_sha(repository, tag)
    if before != after:
        raise ReleaseTransactionError("GitHub tag changed during legacy recovery")
    return before


def _stable_release_inventory(repository: str) -> tuple[ReleaseState, ...]:
    before = _query_release_inventory(repository)
    after = _query_release_inventory(repository)
    if before != after:
        raise ReleaseTransactionError(
            "GitHub release inventory changed during legacy recovery"
        )
    return before


def _stable_release_by_tag(repository: str, tag: str) -> ReleaseState | None:
    before = _query_release_by_tag(repository, tag)
    after = _query_release_by_tag(repository, tag)
    if before != after:
        raise ReleaseTransactionError("GitHub release binding changed during recovery")
    return before


def _verify_legacy_tag_context(
    repository: str,
    plan: LegacyRecoveryPlan,
    *,
    terminal: bool,
) -> ReleaseState | None:
    tagged = _stable_release_by_tag(repository, LEGACY_TAG)
    if terminal != (tagged is not None):
        raise ReleaseTransactionError("latest release binding changed")
    if _stable_legacy_tag_sha(repository, LEGACY_TAG) != plan.target_sha:
        raise ReleaseTransactionError("latest tag target changed")
    if plan.detached_tag is not None and (
        _stable_legacy_tag_sha(repository, plan.detached_tag) is not None
    ):
        raise ReleaseTransactionError("detached release tag unexpectedly has a Git ref")
    return tagged


def _validate_legacy_terminal(
    repository: str,
    expected: LegacyRecoveryPlan | None = None,
) -> LegacyRecoveryPlan:
    if expected is None:
        tagged = _stable_release_by_tag(repository, LEGACY_TAG)
        if tagged is None:
            raise ReleaseTransactionError("latest release is not bound")
        target_sha = _stable_legacy_tag_sha(repository, LEGACY_TAG)
        if target_sha is None:
            raise ReleaseTransactionError("latest tag is absent")
        legacy = _query_legacy_release_by_id(repository, tagged.database_id)
        if legacy is None:
            raise ReleaseTransactionError("latest release disappeared")
        plan = _build_legacy_recovery_plan(legacy, target_sha, terminal=True)
    else:
        plan = expected
        tagged = _verify_legacy_tag_context(repository, plan, terminal=True)
        if tagged is None:
            raise ReleaseTransactionError("latest release is not bound")
        legacy = _query_legacy_release_by_id(repository, plan.release_id)
        if legacy is None:
            raise ReleaseTransactionError("latest release disappeared")
    _legacy_recovery_progress(legacy, plan, terminal=True)
    if tagged.is_latest or replace(tagged, is_latest=False) != legacy.release:
        raise ReleaseTransactionError("published latest release state changed")
    if _verify_legacy_tag_context(repository, plan, terminal=True) != tagged:
        raise ReleaseTransactionError("published latest release changed during query")
    return plan


def _legacy_release_metadata_target(release: ReleaseState) -> str | None:
    if (
        not release.is_draft
        or release.immutable
        or not release.is_prerelease
        or release.is_latest
        or LEGACY_DETACHED_TAG.fullmatch(release.tag_name) is None
        or LEGACY_RELEASE_NAME.fullmatch(release.name) is None
    ):
        return None
    try:
        return _legacy_target_sha(release.name, release.description)
    except ReleaseTransactionError:
        return None


def _has_legacy_release_metadata(release: ReleaseState, target_sha: str) -> bool:
    return _legacy_release_metadata_target(release) == target_sha


def _has_legacy_asset_profile(release: ReleaseState) -> bool:
    def valid_name(asset: ReleaseAsset) -> bool:
        return (
            asset.name == f"justdocs-rollback-{asset.database_id}"
            or asset.name in {"SHA256SUMS.txt", "install.ps1", "install.sh"}
            or LEGACY_WHEEL_NAME.fullmatch(asset.name) is not None
            or re.fullmatch(
                r"justdocs-[0-9A-Za-z][0-9A-Za-z._]*\.tar\.gz",
                asset.name,
            )
            is not None
        )

    return (
        len(release.assets) == 5
        and len({asset.database_id for asset in release.assets}) == 5
        and len({asset.digest for asset in release.assets}) == 5
        and all(
            valid_name(asset)
            and asset.state == "uploaded"
            and asset.digest is not None
            and not asset.label
            for asset in release.assets
        )
    )


def _legacy_detached_candidates(
    repository: str,
    inventory: tuple[ReleaseState, ...],
    target_sha: str,
) -> tuple[ReleaseState, ...]:
    candidates: list[ReleaseState] = []
    for release in inventory:
        if not _has_legacy_release_metadata(release, target_sha):
            continue
        current = _query_release_by_id(repository, release.database_id)
        if current is None or replace(release, assets=current.assets) != current:
            raise ReleaseTransactionError(
                "GitHub release changed during legacy candidate query"
            )
        if not _has_legacy_asset_profile(current):
            raise ReleaseTransactionError("invalid detached latest asset profile")
        candidates.append(current)
    return tuple(candidates)


def _recover_detached(tag: str) -> None:
    repository = _validate_preflight_inputs(tag, "false")
    if repository != LEGACY_REPOSITORY or tag != LEGACY_TAG:
        raise ReleaseTransactionError(
            "detached recovery is restricted to FanaticPythoner/justdocs latest"
        )
    _validate_upload_transport()
    if _stable_release_by_tag(repository, tag) is not None:
        _assert_no_detached_transaction_residue(repository)
        return
    target_sha = _stable_legacy_tag_sha(repository, tag)
    inventory = _stable_release_inventory(repository)
    if target_sha is None:
        if any(
            _legacy_release_metadata_target(release) is not None
            for release in inventory
        ):
            raise ReleaseTransactionError("latest tag is absent")
        _assert_no_detached_transaction_residue(repository)
        return
    candidates = _legacy_detached_candidates(
        repository,
        inventory,
        target_sha,
    )
    if not candidates:
        _assert_no_detached_transaction_residue(repository)
        return
    if len(candidates) != 1:
        raise ReleaseTransactionError("multiple detached latest release candidates")
    candidate = candidates[0]
    legacy = _query_legacy_release_by_id(repository, candidate.database_id)
    if legacy is None:
        raise ReleaseTransactionError("detached latest release disappeared")
    plan = _build_legacy_recovery_plan(legacy, target_sha, terminal=False)
    _verify_legacy_tag_context(repository, plan, terminal=False)

    while True:
        current = _query_legacy_release_by_id(repository, plan.release_id)
        if current is None:
            raise ReleaseTransactionError("detached latest release disappeared")
        progress = _legacy_recovery_progress(current, plan, terminal=False)
        if progress == len(plan.assets):
            break
        _verify_legacy_tag_context(repository, plan, terminal=False)
        current = _query_legacy_release_by_id(repository, plan.release_id)
        if current is None:
            raise ReleaseTransactionError("detached latest release disappeared")
        if _legacy_recovery_progress(current, plan, terminal=False) != progress:
            raise ReleaseTransactionError(
                "detached latest release changed before rename"
            )
        asset_plan = plan.assets[progress]
        current_asset = next(
            asset
            for asset in current.release.assets
            if asset.database_id == asset_plan.original.database_id
        )
        try:
            _rename_asset(repository, current_asset, asset_plan.target_name)
        except ReleaseTransactionInterrupted:
            raise
        except ReleaseTransactionError as error:
            observed = _query_legacy_release_by_id(repository, plan.release_id)
            if observed is None:
                raise ReleaseTransactionError(
                    "detached latest release disappeared after rename"
                ) from error
            observed_progress = _legacy_recovery_progress(
                observed,
                plan,
                terminal=False,
            )
            if observed_progress == progress + 1:
                continue
            raise
        observed = _query_legacy_release_by_id(repository, plan.release_id)
        if (
            observed is None
            or _legacy_recovery_progress(
                observed,
                plan,
                terminal=False,
            )
            != progress + 1
        ):
            raise ReleaseTransactionError(
                "detached latest release rename verification failed"
            )

    _verify_legacy_tag_context(repository, plan, terminal=False)
    current = _query_legacy_release_by_id(repository, plan.release_id)
    if current is None or _legacy_recovery_progress(
        current,
        plan,
        terminal=False,
    ) != len(plan.assets):
        raise ReleaseTransactionError("detached latest release changed before publish")
    payload = _release_payload(
        tag_name=LEGACY_TAG,
        name=plan.name,
        description=plan.description,
        draft=False,
        prerelease=True,
        is_latest=False,
    )
    arguments = (
        "curl",
        "--disable",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--proto",
        "=https",
        "--request",
        "PATCH",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
        f"https://api.github.com/repos/{repository}/releases/{plan.release_id}",
    )
    try:
        _run_curl_with_bytes_input(arguments, _encoded_json(payload))
    except ReleaseTransactionInterrupted:
        raise
    except ReleaseTransactionError as error:
        try:
            _validate_legacy_terminal(repository, plan)
        except ReleaseTransactionError:
            raise error
        _assert_no_detached_transaction_residue(repository)
        return
    _validate_legacy_terminal(repository, plan)
    _assert_no_detached_transaction_residue(repository)


def _post_baseline_releases(
    metadata: TransactionMetadata,
) -> tuple[ReleaseState, ...]:
    baseline = metadata.precreate_release_ids
    if baseline is None:
        raise ReleaseTransactionError("missing pre-create release baseline")
    inventory = _query_release_inventory(metadata.repository)
    inventory_ids = {release.database_id for release in inventory}
    if not set(baseline).issubset(inventory_ids):
        raise ReleaseTransactionError("pre-create GitHub release inventory changed")
    baseline_ids = set(baseline)
    return tuple(
        release for release in inventory if release.database_id not in baseline_ids
    )


def _is_transaction_marker_release(release: ReleaseState) -> bool:
    marker_prefix = f"justdocs release transaction {TRANSACTION_PREFIX}"
    return (
        release.is_draft
        and not release.immutable
        and release.name == release.description
        and release.name.startswith(marker_prefix)
        and len(release.name) > len(marker_prefix)
    )


def _has_transaction_asset_residue(release: ReleaseState) -> bool:
    if (
        release.immutable
        or not release.is_draft
        or not release.tag_name.startswith("untagged-")
    ):
        return False
    return any(
        asset.name == f"justdocs-rollback-{asset.database_id}"
        or TRANSACTION_UPLOAD_ASSET.fullmatch(asset.name) is not None
        for asset in release.assets
    )


def _assert_no_detached_transaction_residue(repository: str) -> None:
    candidates = tuple(
        release
        for release in _query_release_inventory(repository)
        if release.is_draft
        and not release.immutable
        and (
            _is_transaction_marker_release(release)
            or release.tag_name.startswith("untagged-")
        )
    )
    verified: list[int] = []
    for candidate in candidates:
        current = _query_release_by_id(repository, candidate.database_id)
        if current is None or replace(candidate, assets=current.assets) != current:
            raise ReleaseTransactionError(
                "GitHub release inventory changed during transaction residue scan"
            )
        if (
            _is_transaction_marker_release(current)
            or _has_transaction_asset_residue(current)
            or _legacy_release_metadata_target(current) is not None
            and _has_legacy_asset_profile(current)
        ):
            verified.append(current.database_id)
    if verified:
        identifiers = ", ".join(str(identifier) for identifier in sorted(verified))
        raise ReleaseTransactionError(
            f"detached GitHub release transaction residue detected: {identifiers}"
        )


def _is_reserved_transaction_asset_name(name: str) -> bool:
    return name.startswith(("justdocs-rollback-", "justdocs-upload-"))


def _validate_parent(raw_parent: str) -> Path:
    if not raw_parent:
        raise ReleaseTransactionError("invalid transaction parent: expected path")
    parent = Path(os.path.abspath(raw_parent))
    try:
        return _canonical_directory(parent)
    except (OSError, ReleaseTransactionError) as error:
        raise ReleaseTransactionError(
            "invalid transaction parent: expected secure directory"
        ) from error


def _required_open_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_NOFOLLOW", "O_NONBLOCK"):
        value = getattr(os, name, None)
        if type(value) is not int or value == 0:
            raise ReleaseTransactionError(
                f"GitHub release transaction requires os.{name}"
            )
        flags |= value
    return flags


def _directory_open_flags() -> int:
    try:
        return directory_open_flags()
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


@contextmanager
def _open_absolute_directory(path: Path) -> Iterator[int]:
    try:
        with secure_open_absolute_directory(path) as descriptor:
            yield descriptor
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


def _canonical_directory(path: Path) -> Path:
    try:
        return secure_canonical_directory(path)
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


def _canonical_child(raw_path: str | Path) -> Path:
    try:
        return secure_canonical_child(raw_path)
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


def _bind_created_directory(
    created_path: Path,
    expected_parent: Path,
    required_prefix: str,
) -> Path:
    try:
        return secure_bind_created_directory(
            created_path,
            expected_parent,
            required_prefix,
        )
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


@contextmanager
def _open_bound_created_directory(
    created_path: Path,
    expected_parent: Path,
    required_prefix: str,
) -> Iterator[BoundCreatedDirectory]:
    try:
        with secure_open_bound_created_directory(
            created_path,
            expected_parent,
            required_prefix,
        ) as binding:
            yield binding
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


def _verify_bound_created_directory(binding: BoundCreatedDirectory) -> None:
    try:
        secure_verify_bound_created_directory(binding)
    except SecurePathError as error:
        raise ReleaseTransactionError(str(error)) from error


@contextmanager
def _open_bound_directory(path: Path) -> Iterator[int]:
    with _open_absolute_directory(path.parent) as parent_descriptor:
        descriptor = os.open(
            path.name,
            _directory_open_flags(),
            dir_fd=parent_descriptor,
        )
        try:
            yield descriptor
        finally:
            os.close(descriptor)


def _read_regular_bytes_at(directory_descriptor: int, name: str) -> bytes:
    try:
        descriptor = os.open(
            name,
            _required_open_flags(),
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        raise ReleaseTransactionError(f"invalid transaction file: {name}") from error
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ReleaseTransactionError(f"invalid transaction file: {name}")
        return source.read()


def _read_regular_bytes(path: Path) -> bytes:
    try:
        descriptor = os.open(path, _required_open_flags())
    except OSError as error:
        raise ReleaseTransactionError(f"invalid transaction file: {path}") from error
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ReleaseTransactionError(f"invalid transaction file: {path}")
        return source.read()


def _encoded_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _write_json_exclusive_at(
    directory_descriptor: int,
    name: str,
    payload: object,
) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=directory_descriptor,
    )
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(_encoded_json(payload))
        destination.flush()
        os.fsync(destination.fileno())


def _write_request_payload(
    transaction_root: Path,
    metadata: TransactionMetadata,
    name: str,
    payload: object,
) -> Path:
    path = transaction_root / name
    with _open_transaction_directory(
        transaction_root,
        metadata,
    ) as directory_descriptor:
        try:
            mode = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            ).st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(mode):
                raise ReleaseTransactionError("invalid GitHub request payload path")
            os.unlink(name, dir_fd=directory_descriptor)
        _write_json_exclusive_at(directory_descriptor, name, payload)
    return path


def _release_payload(
    *,
    tag_name: str,
    name: str,
    description: str,
    draft: bool,
    prerelease: bool,
    is_latest: bool | None = None,
) -> dict[str, object]:
    if is_latest is None:
        latest: str = "false" if prerelease or draft else "legacy"
    else:
        latest = "true" if is_latest else "false"
    return {
        "tag_name": tag_name,
        "name": name,
        "body": description,
        "draft": draft,
        "prerelease": prerelease,
        "make_latest": latest,
    }


def _patch_release(
    metadata: TransactionMetadata,
    release_id: int,
    transaction_root: Path,
    request_name: str,
    *,
    tag_name: str,
    name: str,
    description: str,
    draft: bool,
    prerelease: bool,
    is_latest: bool | None = None,
) -> None:
    payload = _write_request_payload(
        transaction_root,
        metadata,
        request_name,
        _release_payload(
            tag_name=tag_name,
            name=name,
            description=description,
            draft=draft,
            prerelease=prerelease,
            is_latest=is_latest,
        ),
    )
    _gh(
        "api",
        "-X",
        "PATCH",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        "--input",
        str(payload),
        f"repos/{metadata.repository}/releases/{release_id}",
    )


def _create_release(
    metadata: TransactionMetadata,
    transaction_root: Path,
    marker: str,
) -> ReleaseState:
    payload = _release_payload(
        tag_name=metadata.tag,
        name=marker,
        description=marker,
        draft=True,
        prerelease=metadata.desired_prerelease,
    ) | {
        "target_commitish": metadata.target_sha,
    }
    request = _write_request_payload(
        transaction_root,
        metadata,
        "create.json",
        payload,
    )
    try:
        response = json.loads(
            _gh(
                "api",
                "-X",
                "POST",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {API_VERSION}",
                "--input",
                str(request),
                f"repos/{metadata.repository}/releases",
            )
        )
    except json.JSONDecodeError as error:
        raise ReleaseTransactionError(
            "invalid GitHub release creation response"
        ) from error
    created = _parse_rest_release_metadata(response)
    raw_assets = response.get("assets") if isinstance(response, dict) else None
    if not isinstance(raw_assets, list):
        raise ReleaseTransactionError("invalid GitHub release creation response")
    assets = tuple(_parse_asset(value) for value in raw_assets)
    if len({asset.name for asset in assets}) != len(assets):
        raise ReleaseTransactionError("duplicate GitHub release asset name")
    created = replace(
        created, assets=tuple(sorted(assets, key=lambda asset: asset.name))
    )
    if (
        created.immutable
        or not created.is_draft
        or created.is_latest
        or created.is_prerelease != metadata.desired_prerelease
        or created.name != marker
        or created.description != marker
        or created.assets
    ):
        raise ReleaseTransactionError("GitHub release creation metadata mismatch")
    return created


def _delete_release(repository: str, release_id: int) -> None:
    _gh(
        "api",
        "-X",
        "DELETE",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        f"repos/{repository}/releases/{release_id}",
    )


def _upload_asset(
    repository: str,
    release_id: int,
    path: Path,
    *,
    asset_name: str | None = None,
    label: str = "",
    content_type: str | None = None,
) -> ReleaseAsset:
    media_type = content_type or _asset_media_type(path.name)
    uploaded_name = asset_name or path.name
    query = urlencode({"name": uploaded_name, "label": label})
    endpoint = (
        f"https://uploads.github.com/repos/{repository}/releases/"
        f"{release_id}/assets?{query}"
    )
    try:
        response = json.loads(
            _run_curl_with_regular_input(
                (
                    "curl",
                    "--disable",
                    "--fail-with-body",
                    "--silent",
                    "--show-error",
                    "--proto",
                    "=https",
                    "--request",
                    "POST",
                    "-H",
                    "Accept: application/vnd.github+json",
                    "-H",
                    f"X-GitHub-Api-Version: {API_VERSION}",
                    "-H",
                    f"Content-Type: {media_type}",
                    "--data-binary",
                    "@-",
                    endpoint,
                ),
                path,
            ).stdout
        )
    except json.JSONDecodeError as error:
        raise ReleaseTransactionError("invalid GitHub asset upload response") from error
    asset = _parse_asset(response)
    if (
        asset.name != uploaded_name
        or asset.label != label
        or asset.content_type != media_type
        or asset.state != "uploaded"
    ):
        raise ReleaseTransactionError("GitHub asset upload metadata mismatch")
    return asset


def _asset_media_type(name: str) -> str:
    return mimetypes.guess_type(name, strict=False)[0] or "application/octet-stream"


def _state_payload(state: ReleaseState | None) -> object:
    if state is None:
        return None
    return {
        "database_id": state.database_id,
        "tag_name": state.tag_name,
        "immutable": state.immutable,
        "is_draft": state.is_draft,
        "is_latest": state.is_latest,
        "is_prerelease": state.is_prerelease,
        "name": state.name,
        "description": state.description,
        "assets": [
            {
                "id": asset.database_id,
                "name": asset.name,
                "label": asset.label,
                "content_type": asset.content_type,
                "size": asset.size,
                "digest": asset.digest,
                "state": asset.state,
            }
            for asset in state.assets
        ],
    }


def _state_from_payload(payload: object) -> ReleaseState | None:
    if payload is None:
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "database_id",
        "tag_name",
        "immutable",
        "is_draft",
        "is_latest",
        "is_prerelease",
        "name",
        "description",
        "assets",
    }:
        raise ReleaseTransactionError("invalid persisted release state")
    database_id = payload["database_id"]
    assets = payload["assets"]
    if (
        type(database_id) is not int
        or database_id <= 0
        or not isinstance(payload["tag_name"], str)
        or not payload["tag_name"]
        or not isinstance(payload["name"], str)
        or not isinstance(payload["description"], str)
        or not isinstance(assets, list)
    ):
        raise ReleaseTransactionError("invalid persisted release state")
    parsed_assets = tuple(_parse_asset(asset) for asset in assets)
    if len({asset.name for asset in parsed_assets}) != len(parsed_assets):
        raise ReleaseTransactionError("duplicate persisted release asset")
    return ReleaseState(
        database_id=database_id,
        tag_name=payload["tag_name"],
        immutable=_expect_bool(payload["immutable"], "immutable"),
        is_draft=_expect_bool(payload["is_draft"], "is_draft"),
        is_latest=_expect_bool(payload["is_latest"], "is_latest"),
        is_prerelease=_expect_bool(payload["is_prerelease"], "is_prerelease"),
        name=payload["name"],
        description=payload["description"],
        assets=tuple(sorted(parsed_assets, key=lambda asset: asset.name)),
    )


def _transaction_payload(metadata: TransactionMetadata) -> dict[str, object]:
    return {
        "version": TRANSACTION_VERSION,
        "transaction_name": metadata.transaction_name,
        "root_device": metadata.root_device,
        "root_inode": metadata.root_inode,
        "tag": metadata.tag,
        "repository": metadata.repository,
        "parent": str(metadata.parent),
        "create_or_move_tag": metadata.create_or_move_tag,
        "target_sha": metadata.target_sha,
        "original_tag_sha": metadata.original_tag_sha,
        "phase": metadata.phase,
        "original_release": _state_payload(metadata.original_release),
        "prepared_release": _state_payload(metadata.prepared_release),
        "created_release_id": metadata.created_release_id,
        "precreate_release_ids": (
            list(metadata.precreate_release_ids)
            if metadata.precreate_release_ids is not None
            else None
        ),
        "create_attempted": metadata.create_attempted,
        "desired_name": metadata.desired_name,
        "desired_description": metadata.desired_description,
        "desired_prerelease": metadata.desired_prerelease,
        "desired_asset_digests": dict(metadata.desired_asset_digests),
        "owned_asset_ids": dict(metadata.owned_asset_ids),
    }


def _write_transaction_at(
    directory_descriptor: int,
    metadata: TransactionMetadata,
) -> None:
    _verify_root_identity(directory_descriptor, metadata)
    temporary_name = f".{TRANSACTION_METADATA}.tmp"
    try:
        temporary_mode = os.stat(
            temporary_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        ).st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(temporary_mode):
            raise ReleaseTransactionError("invalid transaction journal temporary path")
        os.unlink(temporary_name, dir_fd=directory_descriptor)
    _write_json_exclusive_at(
        directory_descriptor,
        temporary_name,
        _transaction_payload(metadata),
    )
    _verify_root_identity(directory_descriptor, metadata)
    os.replace(
        temporary_name,
        TRANSACTION_METADATA,
        src_dir_fd=directory_descriptor,
        dst_dir_fd=directory_descriptor,
    )
    os.fsync(directory_descriptor)


def _write_transaction(root: Path, metadata: TransactionMetadata) -> None:
    with _open_transaction_directory(root, metadata) as directory_descriptor:
        _write_transaction_at(
            directory_descriptor,
            metadata,
        )


def _cleanup_bound_preflight_directory(binding: BoundCreatedDirectory) -> None:
    _verify_bound_created_directory(binding)
    entries = tuple(sorted(os.listdir(binding.descriptor)))
    allowed = {TRANSACTION_METADATA, f".{TRANSACTION_METADATA}.tmp"}
    if not set(entries).issubset(allowed):
        raise ReleaseTransactionError("unexpected preflight transaction entry")
    for name in entries:
        file_metadata = os.stat(
            name,
            dir_fd=binding.descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(file_metadata.st_mode):
            raise ReleaseTransactionError("invalid preflight transaction entry")
        os.unlink(name, dir_fd=binding.descriptor)
    os.fsync(binding.descriptor)
    _verify_bound_created_directory(binding)
    os.rmdir(binding.path.name, dir_fd=binding.parent_descriptor)
    os.fsync(binding.parent_descriptor)


def _preflight(
    tag: str,
    raw_parent: str,
    create_or_move_tag_raw: str,
    raw_target_sha: str,
) -> Path:
    repository = _validate_preflight_inputs(tag, create_or_move_tag_raw)
    parent = _validate_parent(raw_parent)
    create_or_move_tag = create_or_move_tag_raw == "true"
    target_sha = _validate_target_sha(raw_target_sha, repository)
    original_tag_sha: str | None = None
    if create_or_move_tag:
        original_tag_sha = _remote_tag_sha(repository, tag)
        _validate_monotonic_tag(repository, tag, original_tag_sha, target_sha)
    elif _resolve_commit(repository, tag) != target_sha:
        raise ReleaseTransactionError("release tag does not target the release commit")
    _query_release_by_tag(repository, tag)
    _assert_no_detached_transaction_residue(repository)
    _validate_upload_transport()
    created_root = Path(tempfile.mkdtemp(prefix=TRANSACTION_PREFIX, dir=parent))
    with _open_bound_created_directory(
        created_root,
        parent,
        TRANSACTION_PREFIX,
    ) as binding:
        transaction_root = binding.path
        metadata = TransactionMetadata(
            transaction_name=binding.path.name,
            root_device=binding.device,
            root_inode=binding.inode,
            tag=tag,
            repository=repository,
            parent=parent,
            create_or_move_tag=create_or_move_tag,
            target_sha=target_sha,
            original_tag_sha=original_tag_sha,
            phase="preflight",
            original_release=None,
            prepared_release=None,
            created_release_id=None,
            precreate_release_ids=None,
            create_attempted=False,
            desired_name="",
            desired_description="",
            desired_prerelease=False,
            desired_asset_digests=(),
            owned_asset_ids=(),
        )
        try:
            _write_transaction_at(binding.descriptor, metadata)
            _verify_bound_created_directory(binding)
        except Exception as preflight_error:
            try:
                _cleanup_bound_preflight_directory(binding)
            except Exception as cleanup_error:
                raise ReleaseTransactionError(
                    f"release preflight failed: {preflight_error}; "
                    f"cleanup failed: {cleanup_error}"
                ) from preflight_error
            raise
    return transaction_root


def _load_transaction(raw_root: str) -> tuple[Path, TransactionMetadata]:
    root = _canonical_child(raw_root)
    if not root.name.startswith(TRANSACTION_PREFIX):
        raise ReleaseTransactionError("invalid transaction root")
    try:
        with _open_bound_directory(root) as root_descriptor:
            opened_root = os.fstat(root_descriptor)
            payload = json.loads(
                _read_regular_bytes_at(
                    root_descriptor,
                    TRANSACTION_METADATA,
                ).decode("utf-8")
            )
    except OSError as error:
        raise ReleaseTransactionError("invalid transaction root") from error
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ReleaseTransactionError("invalid transaction metadata") from error
    expected_keys = {
        "version",
        "transaction_name",
        "root_device",
        "root_inode",
        "tag",
        "repository",
        "parent",
        "create_or_move_tag",
        "target_sha",
        "original_tag_sha",
        "phase",
        "original_release",
        "prepared_release",
        "created_release_id",
        "precreate_release_ids",
        "create_attempted",
        "desired_name",
        "desired_description",
        "desired_prerelease",
        "desired_asset_digests",
        "owned_asset_ids",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ReleaseTransactionError("invalid transaction metadata shape")
    if type(payload["version"]) is not int or payload["version"] != TRANSACTION_VERSION:
        raise ReleaseTransactionError("invalid transaction metadata version")
    if not all(
        isinstance(payload[key], str)
        for key in (
            "tag",
            "transaction_name",
            "repository",
            "parent",
            "target_sha",
            "phase",
            "desired_name",
            "desired_description",
        )
    ):
        raise ReleaseTransactionError("invalid transaction metadata value")
    if (
        type(payload["root_device"]) is not int
        or payload["root_device"] < 0
        or type(payload["root_inode"]) is not int
        or payload["root_inode"] <= 0
        or payload["root_device"] != opened_root.st_dev
        or payload["root_inode"] != opened_root.st_ino
        or type(payload["create_or_move_tag"]) is not bool
        or type(payload["desired_prerelease"]) is not bool
        or type(payload["create_attempted"]) is not bool
        or payload["original_tag_sha"] is not None
        and not isinstance(payload["original_tag_sha"], str)
        or payload["created_release_id"] is not None
        and type(payload["created_release_id"]) is not int
        or type(payload["created_release_id"]) is int
        and payload["created_release_id"] <= 0
        or payload["precreate_release_ids"] is not None
        and (
            not isinstance(payload["precreate_release_ids"], list)
            or any(
                type(release_id) is not int or release_id <= 0
                for release_id in payload["precreate_release_ids"]
            )
            or payload["precreate_release_ids"]
            != sorted(set(payload["precreate_release_ids"]))
        )
        or payload["phase"]
        not in {
            "preflight",
            "prepared",
            "mutating",
            "tagging",
            "committing",
            "committed",
            "rolled_back",
            "rolled_back_with_tag",
        }
        or COMMIT_SHA.fullmatch(payload["target_sha"]) is None
        or payload["transaction_name"] != root.name
        or payload["original_tag_sha"] is not None
        and COMMIT_SHA.fullmatch(payload["original_tag_sha"]) is None
        or not isinstance(payload["desired_asset_digests"], dict)
        or any(
            not isinstance(name, str)
            or not isinstance(digest, str)
            or ASSET_DIGEST.fullmatch(digest) is None
            for name, digest in payload["desired_asset_digests"].items()
        )
        or not isinstance(payload["owned_asset_ids"], dict)
        or any(
            not isinstance(name, str)
            or type(database_id) is not int
            or database_id <= 0
            for name, database_id in payload["owned_asset_ids"].items()
        )
    ):
        raise ReleaseTransactionError("invalid transaction metadata value")
    persisted_parent = Path(payload["parent"])
    if not persisted_parent.is_absolute() or persisted_parent != Path(
        os.path.abspath(persisted_parent)
    ):
        raise ReleaseTransactionError("invalid transaction parent metadata")
    try:
        parent = _canonical_directory(persisted_parent)
    except (OSError, ReleaseTransactionError) as error:
        raise ReleaseTransactionError("invalid transaction parent metadata") from error
    if parent != persisted_parent:
        raise ReleaseTransactionError("invalid transaction parent metadata")
    if root.parent != parent:
        raise ReleaseTransactionError("invalid transaction boundary")
    repository = _validate_preflight_inputs(
        payload["tag"],
        "true" if payload["create_or_move_tag"] else "false",
    )
    original_release = _state_from_payload(payload["original_release"])
    prepared_release = _state_from_payload(payload["prepared_release"])
    if (
        repository != payload["repository"]
        or not payload["create_or_move_tag"]
        and payload["original_tag_sha"] is not None
        or payload["created_release_id"] is not None
        and original_release is not None
        or payload["created_release_id"] is not None
        and payload["phase"]
        not in {
            "mutating",
            "tagging",
            "committing",
            "committed",
            "rolled_back",
            "rolled_back_with_tag",
        }
        or payload["phase"] == "preflight"
        and (
            original_release is not None
            or prepared_release is not None
            or payload["created_release_id"] is not None
            or payload["precreate_release_ids"] is not None
            or payload["create_attempted"]
            or payload["desired_name"]
            or payload["desired_description"]
            or payload["desired_prerelease"]
            or payload["desired_asset_digests"]
            or payload["owned_asset_ids"]
        )
        or payload["phase"] != "preflight"
        and (not payload["desired_name"] or not payload["desired_asset_digests"])
        or original_release is not None
        and (
            payload["precreate_release_ids"] is not None or payload["create_attempted"]
        )
        or payload["created_release_id"] is not None
        and (
            payload["precreate_release_ids"] is None or not payload["create_attempted"]
        )
        or payload["create_attempted"]
        and payload["precreate_release_ids"] is None
        or not set(payload["owned_asset_ids"]).issubset(
            payload["desired_asset_digests"]
        )
        or len(set(payload["owned_asset_ids"].values()))
        != len(payload["owned_asset_ids"])
        or payload["phase"] == "committed"
        and original_release is None
        and payload["created_release_id"] is None
        or payload["phase"] in {"preflight", "prepared", "mutating"}
        and prepared_release is not None
        or payload["phase"] in {"tagging", "committing", "committed"}
        and prepared_release is None
    ):
        raise ReleaseTransactionError("inconsistent transaction metadata")
    return root, TransactionMetadata(
        transaction_name=payload["transaction_name"],
        root_device=payload["root_device"],
        root_inode=payload["root_inode"],
        tag=payload["tag"],
        repository=payload["repository"],
        parent=parent,
        create_or_move_tag=payload["create_or_move_tag"],
        target_sha=payload["target_sha"],
        original_tag_sha=payload["original_tag_sha"],
        phase=payload["phase"],
        original_release=original_release,
        prepared_release=prepared_release,
        created_release_id=payload["created_release_id"],
        precreate_release_ids=(
            tuple(payload["precreate_release_ids"])
            if payload["precreate_release_ids"] is not None
            else None
        ),
        create_attempted=payload["create_attempted"],
        desired_name=payload["desired_name"],
        desired_description=payload["desired_description"],
        desired_prerelease=payload["desired_prerelease"],
        desired_asset_digests=tuple(sorted(payload["desired_asset_digests"].items())),
        owned_asset_ids=tuple(sorted(payload["owned_asset_ids"].items())),
    )


def _snapshot_paths(raw_notes: str, raw_dist: str) -> tuple[Path, Path | None]:
    dist_path = Path(os.path.abspath(raw_dist))
    try:
        dist = _canonical_directory(dist_path)
    except ReleaseTransactionError as error:
        raise ReleaseTransactionError(
            "invalid staged distribution directory"
        ) from error
    stage_root = dist.parent
    if dist.name != "assets":
        raise ReleaseTransactionError("invalid staged distribution directory")
    _run((sys.executable, str(SNAPSHOT_SCRIPT), "verify", str(stage_root)))
    notes: Path | None = None
    if raw_notes:
        notes = _canonical_child(raw_notes)
        if notes != stage_root / "release-notes.md":
            raise ReleaseTransactionError("invalid staged release notes")
    files = tuple(sorted(dist.iterdir(), key=lambda path: path.name))
    if not files or any(path.is_symlink() or not path.is_file() for path in files):
        raise ReleaseTransactionError("invalid staged release assets")
    return dist, notes


def _asset_files(directory: Path) -> tuple[Path, ...]:
    files = tuple(sorted(directory.iterdir(), key=lambda path: path.name))
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise ReleaseTransactionError("invalid release asset backup")
    return files


def _file_payload(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    descriptor = os.open(path, _required_open_flags())
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ReleaseTransactionError(f"invalid staged release asset: {path}")
        while chunk := source.read(HASH_BUFFER_SIZE):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", metadata.st_size


def _local_asset_payloads(files: tuple[Path, ...]) -> dict[str, tuple[str, int]]:
    return {path.name: _file_payload(path) for path in files}


def _verify_staged_inputs(
    files: tuple[Path, ...],
    notes: Path | None,
    expected_description: str,
    expected_assets: dict[str, tuple[str, int]],
) -> None:
    _run(
        (
            sys.executable,
            str(SNAPSHOT_SCRIPT),
            "verify",
            str(files[0].parent.parent),
        )
    )
    description = (
        _read_regular_bytes(notes).decode("utf-8") if notes is not None else ""
    )
    if (
        description != expected_description
        or _local_asset_payloads(files) != expected_assets
    ):
        raise ReleaseTransactionError("staged release inputs changed")


def _delete_assets(assets: tuple[ReleaseAsset, ...], repository: str) -> None:
    for asset in assets:
        _gh(
            "api",
            "--method",
            "DELETE",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
            f"repos/{repository}/releases/assets/{asset.database_id}",
        )


def _retained_asset_name(asset: ReleaseAsset) -> str:
    return f"justdocs-rollback-{asset.database_id}"


def _transaction_asset_name(metadata: TransactionMetadata, final_name: str) -> str:
    encoded = f"{metadata.transaction_name}\0{final_name}".encode("utf-8")
    return f"justdocs-upload-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _rename_asset(
    repository: str,
    asset: ReleaseAsset,
    name: str,
) -> ReleaseAsset:
    try:
        payload = json.loads(
            _gh(
                "api",
                "-X",
                "PATCH",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {API_VERSION}",
                "-f",
                f"name={name}",
                "-f",
                f"label={asset.label}",
                f"repos/{repository}/releases/assets/{asset.database_id}",
            )
        )
    except json.JSONDecodeError as error:
        raise ReleaseTransactionError("invalid GitHub asset rename response") from error
    renamed = _parse_asset(payload)
    if renamed != replace(asset, name=name):
        raise ReleaseTransactionError("GitHub asset rename metadata mismatch")
    return renamed


def _upload_transaction_assets(
    transaction_root: Path,
    metadata: TransactionMetadata,
    release_id: int,
    files: tuple[Path, ...],
) -> TransactionMetadata:
    owned = dict(metadata.owned_asset_ids)
    uploaded: list[tuple[Path, ReleaseAsset]] = []
    temporary_names = {_transaction_asset_name(metadata, path.name) for path in files}
    current = _query_release_by_id(metadata.repository, release_id)
    if current is None or current.database_id != release_id:
        raise ReleaseTransactionError("release disappeared before asset upload")
    if temporary_names & {asset.name for asset in current.assets}:
        raise ReleaseTransactionError("reserved transaction asset name already exists")
    for path in files:
        temporary_name = _transaction_asset_name(metadata, path.name)
        asset = _upload_asset(
            metadata.repository,
            release_id,
            path,
            asset_name=temporary_name,
        )
        if path.name in owned and owned[path.name] != asset.database_id:
            raise ReleaseTransactionError("transaction asset identity changed")
        owned[path.name] = asset.database_id
        metadata = _record_transaction(
            transaction_root,
            metadata,
            owned_asset_ids=tuple(sorted(owned.items())),
        )
        uploaded.append((path, asset))
    for path, asset in uploaded:
        _rename_asset(metadata.repository, asset, path.name)
    return metadata


def _asset_observable(
    asset: ReleaseAsset,
) -> tuple[int, str, str, str, int, str | None, str]:
    return (
        asset.database_id,
        asset.name,
        asset.label,
        asset.content_type,
        asset.size,
        asset.digest,
        asset.state,
    )


def _same_observable_assets(
    left: tuple[ReleaseAsset, ...], right: tuple[ReleaseAsset, ...]
) -> bool:
    return sorted(map(_asset_observable, left)) == sorted(map(_asset_observable, right))


def _release_matches_inputs(
    state: ReleaseState,
    release_name: str,
    prerelease: bool,
    description: str,
    assets: dict[str, tuple[str, int]],
    purge_existing_assets: bool,
) -> bool:
    current_assets = {asset.name: asset for asset in state.assets}
    if (
        state.is_draft
        or state.is_prerelease != prerelease
        or prerelease
        and state.is_latest
        or state.name != release_name
        or state.description != description
        or purge_existing_assets
        and set(current_assets) != set(assets)
        or not purge_existing_assets
        and not set(assets).issubset(current_assets)
    ):
        return False
    return all(
        current_assets[name].digest == digest
        and current_assets[name].size == size
        and not current_assets[name].label
        and current_assets[name].content_type == _asset_media_type(name)
        and current_assets[name].state == "uploaded"
        for name, (digest, size) in assets.items()
    )


def _release_assets_complete(state: ReleaseState) -> bool:
    return all(
        asset.state == "uploaded"
        and asset.digest is not None
        and bool(asset.content_type)
        for asset in state.assets
    )


def _assert_state(
    state: ReleaseState | None,
    *,
    database_id: int,
    draft: bool,
    preserved_assets: tuple[ReleaseAsset, ...],
    new_assets: dict[str, tuple[str, int]],
) -> ReleaseState:
    if state is None:
        raise ReleaseTransactionError("GitHub release disappeared during transaction")
    if state.immutable:
        raise ReleaseTransactionError(
            "GitHub release became immutable during transaction"
        )
    if state.is_draft != draft:
        raise ReleaseTransactionError("GitHub release draft state mismatch")
    if state.database_id != database_id:
        raise ReleaseTransactionError("GitHub release identity changed")
    actual = {asset.name: asset for asset in state.assets}
    preserved = {asset.name: asset for asset in preserved_assets}
    if set(actual) != set(preserved) | set(new_assets):
        raise ReleaseTransactionError("GitHub release asset inventory mismatch")
    for name, asset in preserved.items():
        if actual[name] != asset:
            raise ReleaseTransactionError(
                f"preserved release asset metadata changed: {name}"
            )
    for name, (digest, size) in new_assets.items():
        if (
            actual[name].digest != digest
            or actual[name].size != size
            or actual[name].label
            or actual[name].state != "uploaded"
        ):
            raise ReleaseTransactionError(
                f"published release asset digest mismatch: {name}"
            )
    return state


def _record_transaction(
    root: Path, metadata: TransactionMetadata, **changes: object
) -> TransactionMetadata:
    updated = replace(metadata, **changes)
    _write_transaction(root, updated)
    return updated


def _restore_tag(metadata: TransactionMetadata) -> None:
    if metadata.create_or_move_tag:
        current_sha = _remote_tag_sha(metadata.repository, metadata.tag)
        if current_sha == metadata.original_tag_sha:
            return
        if metadata.original_tag_sha is None and current_sha == metadata.target_sha:
            return
        raise ReleaseTransactionError("remote release tag cannot be restored safely")


def _verify_tag_state(
    metadata: TransactionMetadata,
    *,
    transaction_owned: bool,
) -> None:
    if metadata.create_or_move_tag:
        expected_sha = (
            metadata.target_sha if transaction_owned else metadata.original_tag_sha
        )
        if _remote_tag_sha(metadata.repository, metadata.tag) != expected_sha:
            raise ReleaseTransactionError("remote release tag ownership changed")
    elif _resolve_commit(metadata.repository, metadata.tag) != metadata.target_sha:
        raise ReleaseTransactionError("release tag target changed")


def _advance_transaction_tag(metadata: TransactionMetadata) -> None:
    if not metadata.create_or_move_tag:
        return
    current_sha = _remote_tag_sha(metadata.repository, metadata.tag)
    if current_sha == metadata.target_sha:
        return
    _set_remote_tag(
        metadata.repository,
        metadata.tag,
        metadata.target_sha,
        metadata.original_tag_sha,
    )


def _verify_transaction_tag_owned(metadata: TransactionMetadata) -> None:
    if metadata.create_or_move_tag:
        current_sha = _remote_tag_sha(metadata.repository, metadata.tag)
        if current_sha not in {metadata.original_tag_sha, metadata.target_sha}:
            raise ReleaseTransactionError("remote release tag ownership changed")
    else:
        _verify_tag_state(metadata, transaction_owned=True)


def _assert_recoverable_assets(
    assets: tuple[ReleaseAsset, ...],
    metadata: TransactionMetadata,
) -> None:
    original_assets = {
        asset.name: asset
        for asset in (
            metadata.original_release.assets
            if metadata.original_release is not None
            else ()
        )
    }
    prepared_assets = {
        asset.name: asset
        for asset in (
            metadata.prepared_release.assets
            if metadata.prepared_release is not None
            else ()
        )
    }
    desired_digests = dict(metadata.desired_asset_digests)
    owned_asset_ids = dict(metadata.owned_asset_ids)
    temporary_names = {
        _transaction_asset_name(metadata, final_name): final_name
        for final_name in desired_digests
    }
    for asset in assets:
        original_asset = original_assets.get(asset.name)
        if original_asset is not None and _asset_observable(
            original_asset
        ) == _asset_observable(asset):
            continue
        prepared_asset = prepared_assets.get(asset.name)
        if prepared_asset is not None and _asset_observable(
            prepared_asset
        ) == _asset_observable(asset):
            continue
        if any(
            asset
            == replace(
                original_asset,
                name=_retained_asset_name(original_asset),
            )
            for original_asset in original_assets.values()
        ):
            continue
        final_name = temporary_names.get(asset.name)
        if final_name is None and asset.name in desired_digests:
            final_name = asset.name
        if final_name is not None:
            expected_id = owned_asset_ids.get(final_name)
            temporary = asset.name != final_name
            identity_matches = expected_id == asset.database_id or (
                expected_id is None and temporary
            )
            uploaded = (
                asset.state == "uploaded"
                and asset.digest == desired_digests[final_name]
                and asset.content_type == _asset_media_type(final_name)
            )
            starter = (
                temporary
                and asset.state == "starter"
                and asset.digest is None
                and asset.size == 0
            )
            if identity_matches and not asset.label and (uploaded or starter):
                continue
        raise ReleaseTransactionError(f"release asset ownership changed: {asset.name}")


def _release_matches_original(metadata: TransactionMetadata) -> bool:
    original = metadata.original_release
    if original is not None:
        current = _query_release_by_id(metadata.repository, original.database_id)
        if (
            current is None
            or replace(current, is_latest=original.is_latest) != original
        ):
            return False
        return original.is_draft or (
            _query_release_by_tag(metadata.repository, metadata.tag) == original
        )
    if metadata.created_release_id is not None:
        return (
            _query_release_by_id(metadata.repository, metadata.created_release_id)
            is None
        )
    if metadata.create_attempted:
        return False
    return _query_release_by_tag(metadata.repository, metadata.tag) is None


def _published_matches_transaction(
    metadata: TransactionMetadata,
    *,
    require_target_tag: bool = True,
) -> bool:
    prepared = metadata.prepared_release
    if prepared is None:
        return False
    current = _query_release_by_id(metadata.repository, prepared.database_id)
    if (
        current is None
        or current.database_id != prepared.database_id
        or current.tag_name != metadata.tag
        or current.is_draft
        or current.is_prerelease != metadata.desired_prerelease
        or metadata.desired_prerelease
        and current.is_latest
        or current.name != metadata.desired_name
        or current.description != metadata.desired_description
        or not _same_observable_assets(current.assets, prepared.assets)
    ):
        return False
    tagged = _query_release_by_tag(metadata.repository, metadata.tag)
    if (
        tagged is None
        or metadata.desired_prerelease
        and tagged.is_latest
        or replace(current, is_latest=tagged.is_latest) != tagged
    ):
        return False
    if require_target_tag:
        _verify_tag_state(metadata, transaction_owned=True)
    else:
        _verify_transaction_tag_owned(metadata)
    return True


def _delete_retained_assets_for_commit(
    metadata: TransactionMetadata,
    current: ReleaseState,
) -> ReleaseState:
    prepared = metadata.prepared_release
    if prepared is None or current.database_id != prepared.database_id:
        raise ReleaseTransactionError("prepared release identity changed")
    prepared_by_id = {asset.database_id: asset for asset in prepared.assets}
    original_assets = (
        metadata.original_release.assets
        if metadata.original_release is not None
        else ()
    )
    retained_by_id = {
        asset.database_id: replace(asset, name=_retained_asset_name(asset))
        for asset in original_assets
    }
    retained: list[ReleaseAsset] = []
    for asset in current.assets:
        if asset == prepared_by_id.get(asset.database_id):
            continue
        if asset == retained_by_id.get(asset.database_id):
            retained.append(asset)
            continue
        raise ReleaseTransactionError(
            f"release asset ownership changed during commit: {asset.name}"
        )
    if set(prepared_by_id) - {asset.database_id for asset in current.assets}:
        raise ReleaseTransactionError("prepared release asset disappeared")
    _delete_assets(tuple(retained), metadata.repository)
    updated = _query_release_by_id(metadata.repository, prepared.database_id)
    if (
        updated is None
        or updated.database_id != prepared.database_id
        or not updated.is_draft
        or updated.immutable
        or updated.name != prepared.name
        or updated.description != prepared.description
        or updated.is_prerelease != prepared.is_prerelease
        or not _same_observable_assets(updated.assets, prepared.assets)
    ):
        raise ReleaseTransactionError("prepared release changed during commit")
    return updated


def _complete_commit(
    transaction_root: Path,
    metadata: TransactionMetadata,
) -> TransactionMetadata:
    if metadata.phase not in {"tagging", "committing"}:
        raise ReleaseTransactionError("release transaction is not commit-ready")
    prepared = metadata.prepared_release
    if prepared is None:
        raise ReleaseTransactionError("missing prepared release state")
    _verify_transaction_tag_owned(metadata)
    _advance_transaction_tag(metadata)
    if metadata.phase == "tagging":
        metadata = _record_transaction(
            transaction_root,
            metadata,
            phase="committing",
        )
    if _published_matches_transaction(metadata):
        return _record_transaction(
            transaction_root,
            metadata,
            phase="committed",
        )
    current = _query_release_by_id(metadata.repository, prepared.database_id)
    if (
        current is None
        or current.database_id != prepared.database_id
        or not current.is_draft
        or current.immutable
        or current.name != prepared.name
        or current.description != prepared.description
        or current.is_prerelease != prepared.is_prerelease
    ):
        raise ReleaseTransactionError("prepared release cannot be committed safely")
    _delete_retained_assets_for_commit(metadata, current)
    _patch_release(
        metadata,
        prepared.database_id,
        transaction_root,
        "publish-release.json",
        tag_name=metadata.tag,
        name=metadata.desired_name,
        description=metadata.desired_description,
        draft=False,
        prerelease=metadata.desired_prerelease,
    )
    if not _published_matches_transaction(metadata):
        raise ReleaseTransactionError("published release state is indeterminate")
    return _record_transaction(
        transaction_root,
        metadata,
        phase="committed",
    )


def _restore_release(
    metadata: TransactionMetadata,
    transaction_root: Path,
) -> None:
    original = metadata.original_release
    if original is None:
        raise ReleaseTransactionError("missing original release state")
    tag = metadata.tag
    repository = metadata.repository
    if metadata.create_or_move_tag:
        current_tag_sha = _remote_tag_sha(repository, tag)
        if current_tag_sha not in {metadata.original_tag_sha, metadata.target_sha}:
            raise ReleaseTransactionError("remote release tag ownership changed")
    else:
        _verify_tag_state(metadata, transaction_owned=True)
    current = _query_release_by_id(repository, original.database_id)
    if current is None:
        raise ReleaseTransactionError("release disappeared before rollback")
    if (
        current.immutable
        or current.database_id != original.database_id
        or not current.is_draft
    ):
        raise ReleaseTransactionError("release identity cannot be rolled back")
    marker = _transaction_marker(transaction_root)
    if (
        current.name,
        current.description,
        current.is_prerelease,
    ) != (marker, marker, original.is_prerelease):
        raise ReleaseTransactionError("release metadata ownership changed")
    _assert_recoverable_assets(current.assets, metadata)
    _patch_release(
        metadata,
        original.database_id,
        transaction_root,
        "rollback-draft.json",
        tag_name=tag,
        name=current.name,
        description=current.description,
        draft=True,
        prerelease=current.is_prerelease,
        is_latest=False,
    )
    current = _assert_state(
        _query_release_by_id(repository, original.database_id),
        database_id=original.database_id,
        draft=True,
        preserved_assets=current.assets,
        new_assets={},
    )
    original_assets = {asset.database_id: asset for asset in original.assets}
    retained_assets = {
        asset.database_id: replace(asset, name=_retained_asset_name(asset))
        for asset in original.assets
    }
    transaction_assets = tuple(
        asset
        for asset in current.assets
        if asset != original_assets.get(asset.database_id)
        and asset != retained_assets.get(asset.database_id)
    )
    _delete_assets(transaction_assets, repository)
    current = _query_release_by_id(repository, original.database_id)
    if current is None or current.database_id != original.database_id:
        raise ReleaseTransactionError("release disappeared during asset rollback")
    for asset in current.assets:
        expected_asset = original_assets.get(asset.database_id)
        retained_asset = retained_assets.get(asset.database_id)
        if expected_asset is not None and asset == retained_asset:
            _rename_asset(repository, asset, expected_asset.name)
    restored_assets = _query_release_by_id(repository, original.database_id)
    if (
        restored_assets is None
        or restored_assets.database_id != original.database_id
        or not _same_observable_assets(restored_assets.assets, original.assets)
    ):
        raise ReleaseTransactionError("release asset rollback verification failed")
    _patch_release(
        metadata,
        original.database_id,
        transaction_root,
        "rollback-release.json",
        tag_name=tag,
        name=original.name,
        description=original.description,
        draft=original.is_draft,
        prerelease=original.is_prerelease,
        is_latest=original.is_latest,
    )
    restored = _query_release_by_id(repository, original.database_id)
    if (
        restored is None
        or restored.database_id != original.database_id
        or restored.immutable
        or restored.is_draft != original.is_draft
        or restored.is_prerelease != original.is_prerelease
        or restored.name != original.name
        or restored.description != original.description
        or not _same_observable_assets(restored.assets, original.assets)
    ):
        raise ReleaseTransactionError("release rollback verification failed")
    if replace(restored, is_latest=original.is_latest) != original:
        raise ReleaseTransactionError("release rollback state verification failed")
    if not original.is_draft and _query_release_by_tag(repository, tag) != original:
        raise ReleaseTransactionError("release rollback tag verification failed")
    _restore_tag(metadata)


def _transaction_marker(transaction_root: Path) -> str:
    return _transaction_marker_from_name(transaction_root.name)


def _transaction_marker_from_name(transaction_name: str) -> str:
    return f"justdocs release transaction {transaction_name}"


def _restore_absence(
    metadata: TransactionMetadata,
    transaction_root: Path,
) -> None:
    marker = _transaction_marker(transaction_root)
    if metadata.created_release_id is None:
        if not metadata.create_attempted:
            if _query_release_by_tag(metadata.repository, metadata.tag) is not None:
                raise ReleaseTransactionError(
                    "created release identity is indeterminate"
                )
            _restore_tag(metadata)
            return
        candidates = _post_baseline_releases(metadata)
        if len(candidates) != 1:
            raise ReleaseTransactionError("created release identity is indeterminate")
        candidate = candidates[0]
        if (
            candidate.immutable
            or not candidate.is_draft
            or candidate.name != marker
            or candidate.description != marker
            or candidate.assets
        ):
            raise ReleaseTransactionError("created release identity is indeterminate")
        current = _query_release_by_id(
            metadata.repository,
            candidate.database_id,
        )
        if (
            current is None
            or current.immutable
            or not current.is_draft
            or current.name != marker
            or current.description != marker
            or current.assets
        ):
            raise ReleaseTransactionError("created release identity is indeterminate")
    else:
        current = _query_release_by_id(
            metadata.repository,
            metadata.created_release_id,
        )
    if current is not None:
        identified_by_id = (
            metadata.created_release_id is not None
            and current.database_id == metadata.created_release_id
            and current.is_draft
            and current.name == marker
            and current.description == marker
        )
        identified_by_marker = (
            metadata.created_release_id is None
            and current.is_draft
            and current.name == marker
            and current.description == marker
            and not current.assets
        )
        if current.immutable or not (identified_by_id or identified_by_marker):
            raise ReleaseTransactionError("created release identity is indeterminate")
        _assert_recoverable_assets(current.assets, metadata)
        _delete_release(metadata.repository, current.database_id)
        if _query_release_by_id(metadata.repository, current.database_id) is not None:
            raise ReleaseTransactionError("created release rollback failed")
    _restore_tag(metadata)


def _recover(
    transaction_root: Path,
    metadata: TransactionMetadata,
) -> TransactionMetadata:
    if metadata.phase == "committed":
        if _published_matches_transaction(metadata):
            return metadata
        raise ReleaseTransactionError("committed release state changed")
    if metadata.phase in {"tagging", "committing"}:
        return _complete_commit(transaction_root, metadata)
    if metadata.phase != "mutating":
        raise ReleaseTransactionError("transaction journal is not recoverable")
    if _release_matches_original(metadata):
        _restore_tag(metadata)
    elif metadata.original_release is None:
        _restore_absence(metadata, transaction_root)
    else:
        _restore_release(metadata, transaction_root)
    rollback_phase = "rolled_back"
    if (
        metadata.create_or_move_tag
        and metadata.original_tag_sha is None
        and _remote_tag_sha(metadata.repository, metadata.tag) == metadata.target_sha
    ):
        rollback_phase = "rolled_back_with_tag"
    return _record_transaction(transaction_root, metadata, phase=rollback_phase)


def _publish_absent(
    transaction_root: Path,
    metadata: TransactionMetadata,
    release_name: str,
    prerelease: bool,
    notes: Path | None,
    files: tuple[Path, ...],
    new_assets: dict[str, tuple[str, int]],
) -> None:
    tag = metadata.tag
    repository = metadata.repository
    marker = _transaction_marker(transaction_root)
    _verify_tag_state(metadata, transaction_owned=False)
    if _query_release_by_tag(repository, tag) is not None:
        raise ReleaseTransactionError("release appeared before draft creation")
    _verify_staged_inputs(files, notes, metadata.desired_description, new_assets)
    baseline = tuple(
        release.database_id for release in _query_release_inventory(repository)
    )
    metadata = _record_transaction(
        transaction_root,
        metadata,
        precreate_release_ids=baseline,
    )
    if _query_release_by_tag(repository, tag) is not None:
        raise ReleaseTransactionError("release appeared before draft creation")
    metadata = _record_transaction(
        transaction_root,
        metadata,
        create_attempted=True,
    )
    created_response = _create_release(metadata, transaction_root, marker)
    metadata = _record_transaction(
        transaction_root,
        metadata,
        created_release_id=created_response.database_id,
    )
    created = _query_release_by_id(repository, created_response.database_id)
    if (
        created is None
        or created.immutable
        or not created.is_draft
        or created.name != marker
        or created.description != marker
        or created.assets
    ):
        raise ReleaseTransactionError("draft release creation verification failed")
    _patch_release(
        metadata,
        created.database_id,
        transaction_root,
        "prepare-release.json",
        tag_name=tag,
        name=marker,
        description=marker,
        draft=True,
        prerelease=prerelease,
        is_latest=False,
    )
    prepared = _query_release_by_id(repository, created.database_id)
    if (
        prepared is None
        or prepared.database_id != created.database_id
        or prepared.immutable
        or not prepared.is_draft
        or prepared.is_prerelease != prerelease
        or prepared.name != marker
        or prepared.description != marker
        or prepared.assets
    ):
        raise ReleaseTransactionError("draft release preparation verification failed")
    _verify_staged_inputs(files, notes, metadata.desired_description, new_assets)
    metadata = _upload_transaction_assets(
        transaction_root,
        metadata,
        created.database_id,
        files,
    )
    draft_state = _assert_state(
        _query_release_by_id(repository, created.database_id),
        database_id=created.database_id,
        draft=True,
        preserved_assets=(),
        new_assets=new_assets,
    )
    if (
        draft_state.name != marker
        or draft_state.description != marker
        or draft_state.is_prerelease != prerelease
        or draft_state.is_latest
    ):
        raise ReleaseTransactionError("draft release metadata changed")
    metadata = _record_transaction(
        transaction_root,
        metadata,
        phase="tagging",
        prepared_release=draft_state,
    )
    _complete_commit(transaction_root, metadata)


def _publish_existing(
    original: ReleaseState,
    transaction_root: Path,
    metadata: TransactionMetadata,
    release_name: str,
    prerelease: bool,
    notes: Path | None,
    files: tuple[Path, ...],
    purge_existing_assets: bool,
    new_assets: dict[str, tuple[str, int]],
) -> None:
    tag = metadata.tag
    repository = metadata.repository
    original_names = {asset.name for asset in original.assets}
    new_names = {path.name for path in files}
    selected_names = (
        original_names if purge_existing_assets else original_names & new_names
    )
    selected_assets = tuple(
        asset for asset in original.assets if asset.name in selected_names
    )
    preserved_assets = tuple(
        asset for asset in original.assets if asset.name not in selected_names
    )
    retained_assets = tuple(
        replace(asset, name=_retained_asset_name(asset)) for asset in selected_assets
    )
    retained_names = {asset.name for asset in retained_assets}
    if retained_names & (original_names | new_names):
        raise ReleaseTransactionError("release rollback asset name collision")
    _verify_tag_state(metadata, transaction_owned=False)
    if _query_release_by_tag(repository, tag) != original:
        raise ReleaseTransactionError("release changed before mutation")
    marker = _transaction_marker(transaction_root)
    _patch_release(
        metadata,
        original.database_id,
        transaction_root,
        "prepare-release.json",
        tag_name=tag,
        name=marker,
        description=marker,
        draft=True,
        prerelease=original.is_prerelease,
        is_latest=False,
    )
    marked_draft = _assert_state(
        _query_release_by_id(repository, original.database_id),
        database_id=original.database_id,
        draft=True,
        preserved_assets=original.assets,
        new_assets={},
    )
    if (
        marked_draft.name != marker
        or marked_draft.description != marker
        or marked_draft.is_prerelease != original.is_prerelease
    ):
        raise ReleaseTransactionError("draft release marker verification failed")
    for asset, retained_asset in zip(selected_assets, retained_assets, strict=True):
        _rename_asset(repository, asset, retained_asset.name)
    _assert_state(
        _query_release_by_id(repository, original.database_id),
        database_id=original.database_id,
        draft=True,
        preserved_assets=preserved_assets + retained_assets,
        new_assets={},
    )
    _verify_staged_inputs(files, notes, metadata.desired_description, new_assets)
    metadata = _upload_transaction_assets(
        transaction_root,
        metadata,
        original.database_id,
        files,
    )
    draft_state = _assert_state(
        _query_release_by_id(repository, original.database_id),
        database_id=original.database_id,
        draft=True,
        preserved_assets=preserved_assets + retained_assets,
        new_assets=new_assets,
    )
    if (
        draft_state.name != marker
        or draft_state.description != marker
        or draft_state.is_prerelease != original.is_prerelease
        or draft_state.is_latest
    ):
        raise ReleaseTransactionError("draft release metadata changed")
    prepared_assets = tuple(
        asset for asset in draft_state.assets if asset.name not in retained_names
    )
    metadata = _record_transaction(
        transaction_root,
        metadata,
        phase="tagging",
        prepared_release=replace(draft_state, assets=prepared_assets),
    )
    _complete_commit(transaction_root, metadata)


def _publish(
    raw_root: str,
    release_name: str,
    prerelease_raw: str,
    raw_notes: str,
    raw_dist: str,
    purge_raw: str,
) -> None:
    transaction_root, metadata = _load_transaction(raw_root)
    if metadata.phase != "preflight":
        raise ReleaseTransactionError("transaction has already been executed")
    repository = _validate_publish_inputs(
        metadata.tag,
        release_name,
        prerelease_raw,
        purge_raw,
    )
    if repository != metadata.repository:
        raise ReleaseTransactionError("repository identity changed after preflight")
    dist, notes = _snapshot_paths(raw_notes, raw_dist)
    files = _asset_files(dist)
    if not files:
        raise ReleaseTransactionError("no staged release assets")
    state = _query_release_by_tag(repository, metadata.tag)
    reserved_names = sorted(
        name
        for name in [path.name for path in files]
        + ([asset.name for asset in state.assets] if state is not None else [])
        if _is_reserved_transaction_asset_name(name)
    )
    if reserved_names:
        raise ReleaseTransactionError(
            f"reserved release transaction asset name: {reserved_names[0]}"
        )
    if state is not None and state.is_draft:
        raise ReleaseTransactionError("preexisting draft releases are unsupported")
    prerelease = prerelease_raw == "true"
    expected_description = (
        _read_regular_bytes(notes).decode("utf-8") if notes is not None else ""
    )
    new_assets = _local_asset_payloads(files)
    if state is not None and not _release_assets_complete(state):
        raise ReleaseTransactionError("release contains incomplete asset uploads")
    if state is not None and state.immutable:
        if not _release_matches_inputs(
            state,
            release_name,
            prerelease,
            expected_description,
            new_assets,
            purge_raw == "true",
        ):
            raise ReleaseTransactionError(
                f"release '{metadata.tag}' is immutable and differs from staged inputs"
            )
        _verify_tag_state(metadata, transaction_owned=True)
        metadata = _record_transaction(
            transaction_root,
            metadata,
            phase="prepared",
            original_release=state,
            prepared_release=None,
            desired_name=release_name,
            desired_description=expected_description,
            desired_prerelease=prerelease,
            desired_asset_digests=tuple(
                sorted((name, digest) for name, (digest, _size) in new_assets.items())
            ),
        )
        _record_transaction(
            transaction_root,
            metadata,
            phase="committed",
            prepared_release=state,
        )
        return
    if _query_release_by_tag(repository, metadata.tag) != state:
        raise ReleaseTransactionError("release changed during transaction preparation")
    _verify_tag_state(metadata, transaction_owned=False)
    metadata = _record_transaction(
        transaction_root,
        metadata,
        phase="prepared",
        original_release=state,
        prepared_release=None,
        desired_name=release_name,
        desired_description=expected_description,
        desired_prerelease=prerelease,
        desired_asset_digests=tuple(
            sorted((name, digest) for name, (digest, _size) in new_assets.items())
        ),
    )
    metadata = _record_transaction(transaction_root, metadata, phase="mutating")
    try:
        _verify_staged_inputs(files, notes, metadata.desired_description, new_assets)
        if state is None:
            _publish_absent(
                transaction_root,
                metadata,
                release_name,
                prerelease,
                notes,
                files,
                new_assets,
            )
        else:
            _publish_existing(
                state,
                transaction_root,
                metadata,
                release_name,
                prerelease,
                notes,
                files,
                purge_raw == "true",
                new_assets,
            )
        _, latest_metadata = _load_transaction(str(transaction_root))
        if latest_metadata.phase != "committed" or not _published_matches_transaction(
            latest_metadata,
        ):
            raise ReleaseTransactionError("published release state is indeterminate")
    except Exception as transaction_error:
        try:
            _, recovery_metadata = _load_transaction(str(transaction_root))
            recovered_metadata = _recover(transaction_root, recovery_metadata)
        except Exception as rollback_error:
            raise ReleaseTransactionError(
                f"release transaction failed: {transaction_error}; "
                f"rollback failed: {rollback_error}; "
                f"recovery journal preserved at {transaction_root}"
            ) from transaction_error
        if recovered_metadata.phase == "committed":
            return
        if recovered_metadata.phase == "rolled_back_with_tag":
            raise ReleaseTransactionError(
                "release transaction failed and rollback retained the target tag: "
                f"{transaction_error}"
            ) from transaction_error
        raise ReleaseTransactionError(
            f"release transaction failed and rollback completed: {transaction_error}"
        ) from transaction_error


def _cleanup(raw_root: str, raw_parent: str) -> None:
    parent = _validate_parent(raw_parent)
    root = _canonical_child(raw_root)
    if not root.name.startswith(TRANSACTION_PREFIX) or root.parent != parent:
        raise ReleaseTransactionError("transaction cleanup parent mismatch")
    try:
        initial_metadata = os.lstat(root)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ReleaseTransactionError("invalid transaction cleanup root") from error
    if not stat.S_ISDIR(initial_metadata.st_mode):
        raise ReleaseTransactionError("invalid transaction cleanup root")
    bound_root, initial_transaction = _load_transaction(raw_root)
    if bound_root != root or parent != initial_transaction.parent:
        raise ReleaseTransactionError("transaction cleanup parent mismatch")
    with _transaction_lock(bound_root, initial_transaction):
        bound_metadata = os.lstat(bound_root)
        if (
            bound_metadata.st_dev != initial_metadata.st_dev
            or bound_metadata.st_ino != initial_metadata.st_ino
        ):
            raise ReleaseTransactionError("transaction cleanup root changed")
        locked_root, metadata = _load_transaction(str(bound_root))
        if locked_root != bound_root or metadata.parent != parent:
            raise ReleaseTransactionError("transaction cleanup parent mismatch")
        if metadata.phase in {"mutating", "tagging", "committing"}:
            _recover(bound_root, metadata)
            _, metadata = _load_transaction(str(bound_root))
        if metadata.phase not in TERMINAL_PHASES:
            raise ReleaseTransactionError(
                f"transaction journal requires recovery: {metadata.phase}"
            )
        _run(
            (
                sys.executable,
                str(SNAPSHOT_SCRIPT),
                "cleanup",
                str(bound_root),
                str(parent),
            )
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("tag")
    preflight.add_argument("parent")
    preflight.add_argument("create_or_move_tag")
    preflight.add_argument("target_sha")
    recover_detached = subparsers.add_parser("recover-detached")
    recover_detached.add_argument("tag")
    publish = subparsers.add_parser("publish")
    publish.add_argument("transaction_root")
    publish.add_argument("release_name")
    publish.add_argument("prerelease")
    publish.add_argument("notes_file")
    publish.add_argument("dist_dir")
    publish.add_argument("purge_existing_assets")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("transaction_root")
    cleanup.add_argument("parent")
    return parser


def main() -> int:
    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    arguments = _parser().parse_args()
    try:
        if arguments.command == "preflight":
            print(
                _preflight(
                    arguments.tag,
                    arguments.parent,
                    arguments.create_or_move_tag,
                    arguments.target_sha,
                )
            )
        elif arguments.command == "recover-detached":
            _recover_detached(arguments.tag)
        elif arguments.command == "publish":
            root, metadata = _load_transaction(arguments.transaction_root)
            with _transaction_lock(root, metadata):
                _publish(
                    arguments.transaction_root,
                    arguments.release_name,
                    arguments.prerelease,
                    arguments.notes_file,
                    arguments.dist_dir,
                    arguments.purge_existing_assets,
                )
        else:
            _cleanup(arguments.transaction_root, arguments.parent)
    except (
        ReleaseTransactionError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        print(f"GitHub release transaction failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
