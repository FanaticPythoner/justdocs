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
from typing import Iterator, NoReturn
from urllib.parse import quote, urlencode


SNAPSHOT_SCRIPT = Path(__file__).with_name("stage-release-inputs.py")
VALIDATION_SCRIPT = Path(__file__).with_name("github-repository.sh")
TRANSACTION_PREFIX = "justdocs-release-transaction-"
TRANSACTION_METADATA = "transaction.json"
TRANSACTION_VERSION = 4
HASH_BUFFER_SIZE = 1024 * 1024
RELEASE_QUERY = """query($owner: String!, $name: String!, $tag: String!) {
  repository(owner: $owner, name: $name) {
    release(tagName: $tag) {
      databaseId
      immutable
      isDraft
      isLatest
      isPrerelease
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
    desired_name: str
    desired_description: str
    desired_prerelease: bool
    desired_asset_digests: tuple[tuple[str, str], ...]
    owned_asset_ids: tuple[tuple[str, int], ...]


def _interrupt(signum: int, _frame: object) -> NoReturn:
    raise ReleaseTransactionInterrupted(f"received signal {signum}")


@contextmanager
def _transaction_lock(root: Path) -> Iterator[None]:
    with _open_bound_directory(root) as root_descriptor:
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


def _run_with_regular_input(
    arguments: tuple[str, ...],
    path: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        descriptor = os.open(path, _required_open_flags())
    except OSError as error:
        raise ReleaseTransactionError(f"invalid transaction input: {path}") from error
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ReleaseTransactionError(f"invalid transaction input: {path}")
        try:
            completed = subprocess.run(
                arguments,
                check=True,
                stdin=source,
                text=False,
                capture_output=True,
            )
        except FileNotFoundError as error:
            raise ReleaseTransactionError(
                f"required executable not found: {arguments[0]}"
            ) from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or b"").decode("utf-8", "replace").strip()
            message = f"command failed with exit code {error.returncode}: {arguments[0]}"
            if detail:
                message = f"{message}: {detail}"
            raise ReleaseTransactionError(message) from error
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


def _query_release_metadata(repository: str, tag: str) -> ReleaseState | None:
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
        immutable=_expect_bool(release.get("immutable"), "immutable"),
        is_draft=_expect_bool(release.get("isDraft"), "isDraft"),
        is_latest=_expect_bool(release.get("isLatest"), "isLatest"),
        is_prerelease=_expect_bool(release.get("isPrerelease"), "isPrerelease"),
        name=_expect_string_or_empty(release.get("name"), "name"),
        description=_expect_string_or_empty(release.get("description"), "description"),
        assets=(),
    )


def _query_assets(repository: str, release_id: int) -> tuple[ReleaseAsset, ...]:
    endpoint = f"repos/{repository}/releases/{release_id}/assets?per_page=100"
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
        raise ReleaseTransactionError(
            "invalid GitHub release asset response"
        ) from error
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ReleaseTransactionError("invalid GitHub release asset response")
    assets = tuple(_parse_asset(value) for page in pages for value in page)
    names = [asset.name for asset in assets]
    if len(names) != len(set(names)):
        raise ReleaseTransactionError("duplicate GitHub release asset name")
    return tuple(sorted(assets, key=lambda asset: asset.name))


def _query_release(repository: str, tag: str) -> ReleaseState | None:
    before = _query_release_metadata(repository, tag)
    if before is None:
        return None
    assets = _query_assets(repository, before.database_id)
    after = _query_release_metadata(repository, tag)
    if after != before:
        raise ReleaseTransactionError("GitHub release changed during query")
    return ReleaseState(
        database_id=before.database_id,
        immutable=before.immutable,
        is_draft=before.is_draft,
        is_latest=before.is_latest,
        is_prerelease=before.is_prerelease,
        name=before.name,
        description=before.description,
        assets=assets,
    )


def _validate_parent(raw_parent: str) -> Path:
    if not raw_parent:
        raise ReleaseTransactionError("invalid transaction parent: expected path")
    parent = Path(os.path.abspath(raw_parent))
    try:
        with _open_absolute_directory(parent):
            pass
    except OSError as error:
        raise ReleaseTransactionError(
            "invalid transaction parent: expected directory without symbolic links"
        ) from error
    return parent


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
    flags = os.O_RDONLY
    for name in ("O_DIRECTORY", "O_NOFOLLOW"):
        value = getattr(os, name, None)
        if type(value) is not int or value == 0:
            raise ReleaseTransactionError(
                f"GitHub release transaction requires os.{name}"
            )
        flags |= value
    return flags


@contextmanager
def _open_absolute_directory(path: Path) -> Iterator[int]:
    if not path.is_absolute():
        raise ReleaseTransactionError("invalid absolute transaction directory")
    descriptor = os.open(path.anchor, _directory_open_flags())
    try:
        for component in path.parts[1:]:
            child_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child_descriptor
        yield descriptor
    finally:
        os.close(descriptor)


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
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


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
    name: str,
    payload: object,
) -> Path:
    path = transaction_root / name
    with _open_bound_directory(transaction_root) as directory_descriptor:
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
        "name": name,
        "body": description,
        "draft": draft,
        "prerelease": prerelease,
        "make_latest": latest,
    }


def _patch_release(
    repository: str,
    release_id: int,
    transaction_root: Path,
    request_name: str,
    *,
    name: str,
    description: str,
    draft: bool,
    prerelease: bool,
    is_latest: bool | None = None,
) -> None:
    payload = _write_request_payload(
        transaction_root,
        request_name,
        _release_payload(
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
        f"repos/{repository}/releases/{release_id}",
    )


def _create_release(
    metadata: TransactionMetadata,
    transaction_root: Path,
    marker: str,
) -> None:
    payload = _release_payload(
        name=marker,
        description=marker,
        draft=True,
        prerelease=metadata.desired_prerelease,
    ) | {
        "tag_name": metadata.tag,
        "target_commitish": metadata.target_sha,
    }
    request = _write_request_payload(transaction_root, "create.json", payload)
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
            _run_with_regular_input(
                (
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    "-H",
                    "Accept: application/vnd.github+json",
                    "-H",
                    f"X-GitHub-Api-Version: {API_VERSION}",
                    "-H",
                    f"Content-Type: {media_type}",
                    "--input",
                    "-",
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
        "desired_name": metadata.desired_name,
        "desired_description": metadata.desired_description,
        "desired_prerelease": metadata.desired_prerelease,
        "desired_asset_digests": dict(metadata.desired_asset_digests),
        "owned_asset_ids": dict(metadata.owned_asset_ids),
    }


def _write_transaction(root: Path, metadata: TransactionMetadata) -> None:
    temporary_name = f".{TRANSACTION_METADATA}.tmp"
    with _open_bound_directory(root) as directory_descriptor:
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
                raise ReleaseTransactionError(
                    "invalid transaction journal temporary path"
                )
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        _write_json_exclusive_at(
            directory_descriptor,
            temporary_name,
            _transaction_payload(metadata),
        )
        os.replace(
            temporary_name,
            TRANSACTION_METADATA,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)


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
    _query_release(repository, tag)
    transaction_root = Path(tempfile.mkdtemp(prefix=TRANSACTION_PREFIX, dir=parent))
    try:
        _write_transaction(
            transaction_root,
            TransactionMetadata(
                transaction_name=transaction_root.name,
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
                desired_name="",
                desired_description="",
                desired_prerelease=False,
                desired_asset_digests=(),
                owned_asset_ids=(),
            ),
        )
    except Exception as preflight_error:
        try:
            _run(
                (
                    sys.executable,
                    str(SNAPSHOT_SCRIPT),
                    "cleanup",
                    str(transaction_root),
                    str(parent),
                )
            )
        except Exception as cleanup_error:
            raise ReleaseTransactionError(
                f"release preflight failed: {preflight_error}; "
                f"cleanup failed: {cleanup_error}"
            ) from preflight_error
        raise
    return transaction_root


def _load_transaction(raw_root: str) -> tuple[Path, TransactionMetadata]:
    root = Path(os.path.abspath(raw_root))
    if not root.name.startswith(TRANSACTION_PREFIX):
        raise ReleaseTransactionError("invalid transaction root")
    try:
        with _open_bound_directory(root) as root_descriptor:
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
        type(payload["create_or_move_tag"]) is not bool
        or type(payload["desired_prerelease"]) is not bool
        or payload["original_tag_sha"] is not None
        and not isinstance(payload["original_tag_sha"], str)
        or payload["created_release_id"] is not None
        and type(payload["created_release_id"]) is not int
        or type(payload["created_release_id"]) is int
        and payload["created_release_id"] <= 0
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
    parent = Path(payload["parent"])
    if not parent.is_absolute() or parent != Path(os.path.abspath(parent)):
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
            or payload["desired_name"]
            or payload["desired_description"]
            or payload["desired_prerelease"]
            or payload["desired_asset_digests"]
            or payload["owned_asset_ids"]
        )
        or payload["phase"] != "preflight"
        and (not payload["desired_name"] or not payload["desired_asset_digests"])
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
        desired_name=payload["desired_name"],
        desired_description=payload["desired_description"],
        desired_prerelease=payload["desired_prerelease"],
        desired_asset_digests=tuple(sorted(payload["desired_asset_digests"].items())),
        owned_asset_ids=tuple(sorted(payload["owned_asset_ids"].items())),
    )


def _snapshot_paths(raw_notes: str, raw_dist: str) -> tuple[Path, Path | None]:
    dist_path = Path(raw_dist)
    if dist_path.is_symlink():
        raise ReleaseTransactionError("invalid staged distribution directory")
    dist = dist_path.resolve(strict=True)
    stage_root = dist.parent
    if dist.name != "assets":
        raise ReleaseTransactionError("invalid staged distribution directory")
    _run((sys.executable, str(SNAPSHOT_SCRIPT), "verify", str(stage_root)))
    notes: Path | None = None
    if raw_notes:
        notes_path = Path(raw_notes)
        if notes_path.is_symlink():
            raise ReleaseTransactionError("invalid staged release notes")
        notes = notes_path.resolve(strict=True)
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
    temporary_names = {
        _transaction_asset_name(metadata, path.name) for path in files
    }
    current = _query_release(metadata.repository, metadata.tag)
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
            asset == replace(
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
    current = _query_release(metadata.repository, metadata.tag)
    return current == metadata.original_release


def _published_matches_transaction(
    metadata: TransactionMetadata,
    *,
    require_target_tag: bool = True,
) -> bool:
    prepared = metadata.prepared_release
    if prepared is None:
        return False
    current = _query_release(metadata.repository, metadata.tag)
    if (
        current is None
        or current.database_id != prepared.database_id
        or current.is_draft
        or current.is_prerelease != metadata.desired_prerelease
        or metadata.desired_prerelease
        and current.is_latest
        or current.name != metadata.desired_name
        or current.description != metadata.desired_description
        or not _same_observable_assets(current.assets, prepared.assets)
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
    updated = _query_release(metadata.repository, metadata.tag)
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
    current = _query_release(metadata.repository, metadata.tag)
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
        metadata.repository,
        prepared.database_id,
        transaction_root,
        "publish-release.json",
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
    current = _query_release(repository, tag)
    if current is None:
        raise ReleaseTransactionError("release disappeared before rollback")
    if current.immutable or current.database_id != original.database_id:
        raise ReleaseTransactionError("release identity cannot be rolled back")
    if (
        current.name,
        current.description,
        current.is_prerelease,
    ) not in {
        (original.name, original.description, original.is_prerelease),
        (
            metadata.desired_name,
            metadata.desired_description,
            metadata.desired_prerelease,
        ),
    }:
        raise ReleaseTransactionError("release metadata ownership changed")
    _assert_recoverable_assets(current.assets, metadata)
    _patch_release(
        repository,
        original.database_id,
        transaction_root,
        "rollback-draft.json",
        name=current.name,
        description=current.description,
        draft=True,
        prerelease=current.is_prerelease,
        is_latest=False,
    )
    current = _assert_state(
        _query_release(repository, tag),
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
    current = _query_release(repository, tag)
    if current is None or current.database_id != original.database_id:
        raise ReleaseTransactionError("release disappeared during asset rollback")
    for asset in current.assets:
        expected_asset = original_assets.get(asset.database_id)
        retained_asset = retained_assets.get(asset.database_id)
        if expected_asset is not None and asset == retained_asset:
            _rename_asset(repository, asset, expected_asset.name)
    restored_assets = _query_release(repository, tag)
    if (
        restored_assets is None
        or restored_assets.database_id != original.database_id
        or not _same_observable_assets(restored_assets.assets, original.assets)
    ):
        raise ReleaseTransactionError("release asset rollback verification failed")
    _patch_release(
        repository,
        original.database_id,
        transaction_root,
        "rollback-release.json",
        name=original.name,
        description=original.description,
        draft=original.is_draft,
        prerelease=original.is_prerelease,
        is_latest=original.is_latest,
    )
    restored = _query_release(repository, tag)
    if (
        restored is None
        or restored.database_id != original.database_id
        or restored.immutable
        or restored.is_draft != original.is_draft
        or restored.is_latest != original.is_latest
        or restored.is_prerelease != original.is_prerelease
        or restored.name != original.name
        or restored.description != original.description
        or not _same_observable_assets(restored.assets, original.assets)
    ):
        raise ReleaseTransactionError("release rollback verification failed")
    _restore_tag(metadata)


def _transaction_marker(transaction_root: Path) -> str:
    return f"justdocs release transaction {transaction_root.name}"


def _restore_absence(
    metadata: TransactionMetadata,
    transaction_root: Path,
) -> None:
    current = _query_release(metadata.repository, metadata.tag)
    if current is not None:
        marker = _transaction_marker(transaction_root)
        identified_by_id = (
            metadata.created_release_id is not None
            and current.database_id == metadata.created_release_id
            and (current.name, current.description)
            in {
                (marker, marker),
                (metadata.desired_name, metadata.desired_description),
            }
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
        if _query_release(metadata.repository, metadata.tag) is not None:
            raise ReleaseTransactionError("created release rollback failed")
    _restore_tag(metadata)


def _recover(
    transaction_root: Path,
    metadata: TransactionMetadata,
) -> TransactionMetadata:
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
    if _query_release(repository, tag) is not None:
        raise ReleaseTransactionError("release appeared before draft creation")
    _verify_staged_inputs(files, notes, metadata.desired_description, new_assets)
    _create_release(metadata, transaction_root, marker)
    created = _query_release(repository, tag)
    if (
        created is None
        or created.immutable
        or not created.is_draft
        or created.name != marker
        or created.description != marker
        or created.assets
    ):
        raise ReleaseTransactionError("draft release creation verification failed")
    metadata = _record_transaction(
        transaction_root,
        metadata,
        created_release_id=created.database_id,
    )
    _patch_release(
        repository,
        created.database_id,
        transaction_root,
        "prepare-release.json",
        name=release_name,
        description=metadata.desired_description,
        draft=True,
        prerelease=prerelease,
        is_latest=False,
    )
    prepared = _query_release(repository, tag)
    if (
        prepared is None
        or prepared.database_id != created.database_id
        or prepared.immutable
        or not prepared.is_draft
        or prepared.is_prerelease != prerelease
        or prepared.name != release_name
        or prepared.description != metadata.desired_description
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
        _query_release(repository, tag),
        database_id=created.database_id,
        draft=True,
        preserved_assets=(),
        new_assets=new_assets,
    )
    if (
        draft_state.name != release_name
        or draft_state.description != metadata.desired_description
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
    if _query_release(repository, tag) != original:
        raise ReleaseTransactionError("release changed before mutation")
    _patch_release(
        repository,
        original.database_id,
        transaction_root,
        "prepare-release.json",
        name=original.name,
        description=original.description,
        draft=True,
        prerelease=original.is_prerelease,
        is_latest=False,
    )
    _assert_state(
        _query_release(repository, tag),
        database_id=original.database_id,
        draft=True,
        preserved_assets=original.assets,
        new_assets={},
    )
    for asset, retained_asset in zip(selected_assets, retained_assets, strict=True):
        _rename_asset(repository, asset, retained_asset.name)
    _assert_state(
        _query_release(repository, tag),
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
        _query_release(repository, tag),
        database_id=original.database_id,
        draft=True,
        preserved_assets=preserved_assets + retained_assets,
        new_assets=new_assets,
    )
    if (
        draft_state.name != original.name
        or draft_state.description != original.description
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
    state = _query_release(repository, metadata.tag)
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
    if _query_release(repository, metadata.tag) != state:
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
    root, metadata = _load_transaction(raw_root)
    parent = _validate_parent(raw_parent)
    if parent != metadata.parent:
        raise ReleaseTransactionError("transaction cleanup parent mismatch")
    if metadata.phase in {"mutating", "tagging", "committing"}:
        _recover(root, metadata)
        _, metadata = _load_transaction(str(root))
    if metadata.phase not in TERMINAL_PHASES:
        raise ReleaseTransactionError(
            f"transaction journal requires recovery: {metadata.phase}"
        )
    _run(
        (
            sys.executable,
            str(SNAPSHOT_SCRIPT),
            "cleanup",
            str(root),
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
        elif arguments.command == "publish":
            root, _ = _load_transaction(arguments.transaction_root)
            with _transaction_lock(root):
                _publish(
                    arguments.transaction_root,
                    arguments.release_name,
                    arguments.prerelease,
                    arguments.notes_file,
                    arguments.dist_dir,
                    arguments.purge_existing_assets,
                )
        else:
            root, _ = _load_transaction(arguments.transaction_root)
            with _transaction_lock(root):
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
