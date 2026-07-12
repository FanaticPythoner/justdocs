#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NamedTuple
from urllib.parse import quote

from packaging.version import InvalidVersion, Version


MAX_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15.0
HASH_BUFFER_SIZE = 1024 * 1024


class PyPIArtifactError(RuntimeError):
    pass


class PyPIRemoteError(PyPIArtifactError):
    pass


class PyPIArtifactMismatchError(PyPIArtifactError):
    pass


class LocalArtifact(NamedTuple):
    descriptor: int
    digest: str
    size: int


def _required_os_flag(name: str) -> int:
    value = getattr(os, name, None)
    if type(value) is not int or value == 0:
        raise PyPIArtifactError(f"PyPI artifact check requires os.{name}")
    return value


def _regular_read_flags() -> int:
    return (
        os.O_RDONLY | _required_os_flag("O_NOFOLLOW") | _required_os_flag("O_NONBLOCK")
    )


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb") as source:
        while chunk := source.read(HASH_BUFFER_SIZE):
            digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


@contextmanager
def _open_local_artifacts(
    directory: Path,
) -> Iterator[dict[str, LocalArtifact]]:
    directory_flags = (
        os.O_RDONLY | _required_os_flag("O_DIRECTORY") | _required_os_flag("O_NOFOLLOW")
    )
    try:
        directory_descriptor = os.open(directory, directory_flags)
    except OSError as error:
        raise PyPIArtifactError("invalid artifacts directory") from error
    descriptors: list[int] = []
    try:
        names: list[str] = []
        with os.scandir(directory_descriptor) as entries:
            for entry in entries:
                if entry.name.endswith((".whl", ".tar.gz")):
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        raise PyPIArtifactError(
                            "invalid Python distribution artifact inventory"
                        )
                    names.append(entry.name)
        if not names or len(names) != len(set(names)):
            raise PyPIArtifactError(
                "invalid Python distribution artifact inventory"
            )
        artifacts: dict[str, LocalArtifact] = {}
        for name in sorted(names):
            try:
                descriptor = os.open(
                    name,
                    _regular_read_flags(),
                    dir_fd=directory_descriptor,
                )
            except OSError as error:
                raise PyPIArtifactError(
                    "invalid Python distribution artifact inventory"
                ) from error
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PyPIArtifactError(
                    "invalid Python distribution artifact inventory"
                )
            artifacts[name] = LocalArtifact(
                descriptor=descriptor,
                digest=_sha256_descriptor(descriptor),
                size=metadata.st_size,
            )
        yield artifacts
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        os.close(directory_descriptor)


def _read_remote(
    package: str,
    version: str,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, object] | None:
    url = (
        f"https://pypi.org/pypi/{quote(package, safe='')}/"
        f"{quote(version, safe='')}/json"
    )
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "justdocs-release"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            encoded = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise PyPIRemoteError(f"PyPI query failed with HTTP {error.code}") from error
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise PyPIRemoteError(f"PyPI query failed: {error}") from error
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise PyPIRemoteError("PyPI response exceeds 4194304 bytes")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PyPIRemoteError("invalid PyPI JSON response") from error
    if not isinstance(payload, dict):
        raise PyPIRemoteError("invalid PyPI response shape")
    return payload


def publication_state(
    package: str,
    version: str,
    artifacts_directory: Path,
) -> tuple[str, tuple[str, ...]]:
    with _open_local_artifacts(artifacts_directory) as artifacts:
        local = {name: artifact.digest for name, artifact in artifacts.items()}
        return _publication_state(package, version, local)


def _publication_state(
    package: str,
    version: str,
    local: dict[str, str],
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> tuple[str, tuple[str, ...]]:
    try:
        expected_version = Version(version)
    except InvalidVersion as error:
        raise PyPIArtifactError(f"invalid package version '{version}'") from error
    payload = _read_remote(package, version, request_timeout_seconds)
    if payload is None:
        return "absent", tuple(sorted(local))
    info = payload.get("info")
    urls = payload.get("urls")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("version"), str)
        or not isinstance(urls, list)
    ):
        raise PyPIRemoteError("invalid PyPI version metadata")
    try:
        published_version = Version(info["version"])
    except InvalidVersion as error:
        raise PyPIRemoteError("invalid PyPI version metadata") from error
    if published_version != expected_version:
        raise PyPIRemoteError("PyPI version metadata mismatch")
    remote: dict[str, str] = {}
    for value in urls:
        if not isinstance(value, dict):
            raise PyPIRemoteError("invalid PyPI artifact metadata")
        filename = value.get("filename")
        digests = value.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if (
            not isinstance(filename, str)
            or not filename
            or filename in remote
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise PyPIRemoteError("invalid PyPI artifact metadata")
        remote[filename] = digest
    unexpected = set(remote) - set(local)
    mismatched = {
        name for name in set(remote) & set(local) if remote[name] != local[name]
    }
    if unexpected or mismatched:
        raise PyPIArtifactMismatchError(
            f"PyPI artifact mismatch: unexpected={sorted(unexpected)}, "
            f"mismatched={sorted(mismatched)}"
        )
    missing = tuple(sorted(set(local) - set(remote)))
    return ("partial", missing) if missing else ("exact", ())


def _stage_bound_missing(
    destination: Path,
    missing: tuple[str, ...],
    artifacts: dict[str, LocalArtifact],
) -> None:
    if not missing:
        return
    if destination.exists() or destination.is_symlink():
        raise PyPIArtifactError("PyPI staging destination already exists")
    created_names: list[str] = []
    created_destination = False
    try:
        destination.mkdir()
        created_destination = True
        for name in missing:
            artifact = artifacts.get(name)
            if artifact is None:
                raise PyPIArtifactError(f"missing local PyPI artifact '{name}'")
            target = destination / name
            digest = hashlib.sha256()
            copied_size = 0
            os.lseek(artifact.descriptor, 0, os.SEEK_SET)
            target_descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
            )
            created_names.append(name)
            try:
                with os.fdopen(target_descriptor, "wb") as output:
                    target_descriptor = -1
                    with os.fdopen(os.dup(artifact.descriptor), "rb") as source:
                        while chunk := source.read(HASH_BUFFER_SIZE):
                            digest.update(chunk)
                            copied_size += len(chunk)
                            output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if target_descriptor >= 0:
                    os.close(target_descriptor)
            os.lseek(artifact.descriptor, 0, os.SEEK_SET)
            if digest.hexdigest() != artifact.digest or copied_size != artifact.size:
                raise PyPIArtifactError(
                    f"PyPI staging checksum mismatch for '{name}'"
                )
    except (OSError, PyPIArtifactError) as error:
        try:
            for name in created_names:
                (destination / name).unlink(missing_ok=True)
            if created_destination:
                destination.rmdir()
        except OSError as cleanup_error:
            raise PyPIArtifactError(
                f"PyPI staging failed: {error}; cleanup failed: {cleanup_error}"
            ) from error
        if isinstance(error, PyPIArtifactError):
            raise
        raise PyPIArtifactError(f"PyPI staging failed: {error}") from error


def _stage_missing(
    artifacts_directory: Path,
    destination: Path,
    missing: tuple[str, ...],
) -> None:
    with _open_local_artifacts(artifacts_directory) as artifacts:
        _stage_bound_missing(destination, missing, artifacts)


def _wait_for_exact(
    package: str,
    version: str,
    local: dict[str, str],
    interval_seconds: float,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_detail = "no PyPI response"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PyPIArtifactError(
                f"PyPI exact artifact verification expired: {last_detail}"
            )
        try:
            state, _missing = _publication_state(
                package,
                version,
                local,
                min(REQUEST_TIMEOUT_SECONDS, remaining),
            )
        except PyPIRemoteError as error:
            last_detail = str(error)
        else:
            if state == "exact":
                return state
            last_detail = f"PyPI artifact state is '{state}'"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PyPIArtifactError(
                f"PyPI exact artifact verification expired: {last_detail}"
            )
        time.sleep(min(interval_seconds, remaining))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--stage-dir")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    arguments = parser.parse_args()
    try:
        for name in ("interval_seconds", "timeout_seconds"):
            value = getattr(arguments, name)
            if not math.isfinite(value) or value <= 0:
                raise PyPIArtifactError(
                    f"--{name.replace('_', '-')} must be a positive finite number"
                )
        with _open_local_artifacts(Path(arguments.artifacts_dir)) as artifacts:
            local = {name: artifact.digest for name, artifact in artifacts.items()}
            if arguments.wait:
                state = _wait_for_exact(
                    arguments.package,
                    arguments.version,
                    local,
                    arguments.interval_seconds,
                    arguments.timeout_seconds,
                )
                missing: tuple[str, ...] = ()
            else:
                state, missing = _publication_state(
                    arguments.package,
                    arguments.version,
                    local,
                )
            if arguments.stage_dir:
                _stage_bound_missing(
                    Path(arguments.stage_dir),
                    missing,
                    artifacts,
                )
    except PyPIArtifactError as error:
        parser.exit(2, f"PyPI artifact check failed: {error}\n")
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
