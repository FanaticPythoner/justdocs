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


class _WindowsFileIdentity(NamedTuple):
    volume_serial_number: int
    file_id: bytes


class _WindowsHandleState(NamedTuple):
    identity: _WindowsFileIdentity
    attributes: int
    size: int
    last_write_time: int


class _WindowsDirectoryBinding(NamedTuple):
    handle: int
    state: _WindowsHandleState


if os.name == "nt":
    import ctypes as _ctypes
    import msvcrt as _msvcrt
    from ctypes import wintypes as _wintypes

    class _WindowsHandleInformation(_ctypes.Structure):
        _fields_ = (
            ("attributes", _wintypes.DWORD),
            ("creation_time", _wintypes.FILETIME),
            ("last_access_time", _wintypes.FILETIME),
            ("last_write_time", _wintypes.FILETIME),
            ("volume_serial_number", _wintypes.DWORD),
            ("file_size_high", _wintypes.DWORD),
            ("file_size_low", _wintypes.DWORD),
            ("number_of_links", _wintypes.DWORD),
            ("file_index_high", _wintypes.DWORD),
            ("file_index_low", _wintypes.DWORD),
        )

    class _WindowsFileId128(_ctypes.Structure):
        _fields_ = (("identifier", _ctypes.c_ubyte * 16),)

    class _WindowsFileIdInformation(_ctypes.Structure):
        _fields_ = (
            ("volume_serial_number", _ctypes.c_uint64),
            ("file_id", _WindowsFileId128),
        )

    class _WindowsApi:
        _GENERIC_READ = 0x80000000
        _FILE_READ_ATTRIBUTES = 0x00000080
        _FILE_SHARE_READ = 0x00000001
        _FILE_SHARE_WRITE = 0x00000002
        _OPEN_EXISTING = 3
        _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
        _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
        _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
        _FILE_TYPE_DISK = 0x0001
        _FILE_ID_INFO = 18

        def __init__(self) -> None:
            self._invalid_handle = _ctypes.c_void_p(-1).value
            self._kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel32.CreateFileW.argtypes = (
                _wintypes.LPCWSTR,
                _wintypes.DWORD,
                _wintypes.DWORD,
                _wintypes.LPVOID,
                _wintypes.DWORD,
                _wintypes.DWORD,
                _wintypes.HANDLE,
            )
            self._kernel32.CreateFileW.restype = _wintypes.HANDLE
            self._kernel32.GetFileInformationByHandle.argtypes = (
                _wintypes.HANDLE,
                _ctypes.POINTER(_WindowsHandleInformation),
            )
            self._kernel32.GetFileInformationByHandle.restype = _wintypes.BOOL
            self._kernel32.GetFileInformationByHandleEx.argtypes = (
                _wintypes.HANDLE,
                _ctypes.c_int,
                _wintypes.LPVOID,
                _wintypes.DWORD,
            )
            self._kernel32.GetFileInformationByHandleEx.restype = _wintypes.BOOL
            self._kernel32.GetFileType.argtypes = (_wintypes.HANDLE,)
            self._kernel32.GetFileType.restype = _wintypes.DWORD
            self._kernel32.CloseHandle.argtypes = (_wintypes.HANDLE,)
            self._kernel32.CloseHandle.restype = _wintypes.BOOL

        def state(self, handle: int) -> _WindowsHandleState:
            information = _WindowsHandleInformation()
            if not self._kernel32.GetFileInformationByHandle(
                handle,
                _ctypes.byref(information),
            ):
                raise _ctypes.WinError(_ctypes.get_last_error())
            file_id_information = _WindowsFileIdInformation()
            if not self._kernel32.GetFileInformationByHandleEx(
                handle,
                self._FILE_ID_INFO,
                _ctypes.byref(file_id_information),
                _ctypes.sizeof(file_id_information),
            ):
                raise _ctypes.WinError(_ctypes.get_last_error())
            return _WindowsHandleState(
                identity=_WindowsFileIdentity(
                    volume_serial_number=file_id_information.volume_serial_number,
                    file_id=bytes(file_id_information.file_id.identifier),
                ),
                attributes=information.attributes,
                size=(information.file_size_high << 32) | information.file_size_low,
                last_write_time=(information.last_write_time.dwHighDateTime << 32)
                | information.last_write_time.dwLowDateTime,
            )

        def open_path(
            self,
            path: str,
            *,
            directory_required: bool,
        ) -> tuple[int, _WindowsHandleState]:
            desired_access = self._FILE_READ_ATTRIBUTES
            share_mode = self._FILE_SHARE_READ | self._FILE_SHARE_WRITE
            flags = self._FILE_FLAG_OPEN_REPARSE_POINT
            if directory_required:
                flags |= self._FILE_FLAG_BACKUP_SEMANTICS
            else:
                desired_access |= self._GENERIC_READ
                share_mode = self._FILE_SHARE_READ
            handle = self._kernel32.CreateFileW(
                path,
                desired_access,
                share_mode,
                None,
                self._OPEN_EXISTING,
                flags,
                None,
            )
            if handle == self._invalid_handle:
                raise _ctypes.WinError(_ctypes.get_last_error())
            try:
                state = self.state(handle)
                is_directory = bool(state.attributes & self._FILE_ATTRIBUTE_DIRECTORY)
                if (
                    self._kernel32.GetFileType(handle) != self._FILE_TYPE_DISK
                    or state.attributes & self._FILE_ATTRIBUTE_REPARSE_POINT
                    or is_directory != directory_required
                ):
                    raise PyPIArtifactError(
                        "invalid Python distribution artifact inventory"
                    )
                return handle, state
            except BaseException:
                self.close(handle)
                raise

        def close(self, handle: int) -> None:
            if not self._kernel32.CloseHandle(handle):
                raise _ctypes.WinError(_ctypes.get_last_error())

        def descriptor(self, handle: int) -> int:
            return _msvcrt.open_osfhandle(
                handle,
                os.O_RDONLY
                | _required_os_flag("O_BINARY")
                | _required_os_flag("O_NOINHERIT"),
            )

        def native_handle(self, descriptor: int) -> int:
            return _msvcrt.get_osfhandle(descriptor)

    _WINDOWS_API = _WindowsApi()


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


def _distribution_artifact_names(
    directory: str | int | os.PathLike[str],
) -> tuple[str, ...]:
    names: list[str] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.endswith((".whl", ".tar.gz")):
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise PyPIArtifactError(
                        "invalid Python distribution artifact inventory"
                    )
                names.append(entry.name)
    if not names or len(names) != len(set(names)):
        raise PyPIArtifactError("invalid Python distribution artifact inventory")
    return tuple(sorted(names))


@contextmanager
def _open_posix_local_artifacts(
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
        names = _distribution_artifact_names(directory_descriptor)
        artifacts: dict[str, LocalArtifact] = {}
        for name in names:
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


@contextmanager
def _open_windows_local_artifacts(
    directory: Path,
) -> Iterator[dict[str, LocalArtifact]]:
    directory_path = os.path.abspath(os.fspath(directory))
    directory_bindings: list[_WindowsDirectoryBinding] = []
    descriptors: list[int] = []
    try:
        try:
            path = Path(directory_path)
            ancestor_paths = (*reversed(path.parents), path)
            for ancestor_path in ancestor_paths:
                handle, state = _WINDOWS_API.open_path(
                    os.fspath(ancestor_path),
                    directory_required=True,
                )
                directory_bindings.append(
                    _WindowsDirectoryBinding(handle=handle, state=state)
                )
        except (OSError, PyPIArtifactError) as error:
            raise PyPIArtifactError("invalid artifacts directory") from error
        directory_binding = directory_bindings[-1]
        names = _distribution_artifact_names(directory_path)
        artifacts: dict[str, LocalArtifact] = {}
        for name in names:
            artifact_path = os.path.join(directory_path, name)
            handle: int | None = None
            try:
                handle, initial_state = _WINDOWS_API.open_path(
                    artifact_path,
                    directory_required=False,
                )
                descriptor = _WINDOWS_API.descriptor(handle)
                handle = None
            except (OSError, PyPIArtifactError) as error:
                if handle is not None:
                    _WINDOWS_API.close(handle)
                raise PyPIArtifactError(
                    "invalid Python distribution artifact inventory"
                ) from error
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PyPIArtifactError(
                    "invalid Python distribution artifact inventory"
                )
            digest = _sha256_descriptor(descriptor)
            final_state = _WINDOWS_API.state(_WINDOWS_API.native_handle(descriptor))
            if final_state != initial_state or metadata.st_size != initial_state.size:
                raise PyPIArtifactError(
                    "Python distribution artifact changed while binding"
                )
            artifacts[name] = LocalArtifact(
                descriptor=descriptor,
                digest=digest,
                size=initial_state.size,
            )
        if _distribution_artifact_names(directory_path) != names:
            raise PyPIArtifactError(
                "Python distribution artifact inventory changed while binding"
            )
        for binding in directory_bindings:
            bound_state = _WINDOWS_API.state(binding.handle)
            if (
                bound_state.identity != binding.state.identity
                or bound_state.attributes != binding.state.attributes
            ):
                raise PyPIArtifactError(
                    "Python distribution artifact path changed while binding"
                )
        if _WINDOWS_API.state(directory_binding.handle) != directory_binding.state:
            raise PyPIArtifactError(
                "Python distribution artifact directory changed while binding"
            )
        yield artifacts
    except OSError as error:
        raise PyPIArtifactError(
            "invalid Python distribution artifact inventory"
        ) from error
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        for binding in reversed(directory_bindings):
            _WINDOWS_API.close(binding.handle)


@contextmanager
def _open_local_artifacts(
    directory: Path,
) -> Iterator[dict[str, LocalArtifact]]:
    opener = (
        _open_windows_local_artifacts
        if os.name == "nt"
        else _open_posix_local_artifacts
    )
    with opener(directory) as artifacts:
        yield artifacts


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
                raise PyPIArtifactError(f"PyPI staging checksum mismatch for '{name}'")
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
