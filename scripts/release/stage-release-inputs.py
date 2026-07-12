#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

try:
    from secure_posix_paths import (
        SecurePathError,
        canonical_child as secure_canonical_child,
        canonical_directory as secure_canonical_directory,
        directory_open_flags,
        open_absolute_directory as secure_open_absolute_directory,
    )
except ModuleNotFoundError as import_error:
    if import_error.name != "secure_posix_paths":
        raise
    from scripts.release.secure_posix_paths import (
        SecurePathError,
        canonical_child as secure_canonical_child,
        canonical_directory as secure_canonical_directory,
        directory_open_flags,
        open_absolute_directory as secure_open_absolute_directory,
    )


MANIFEST_NAME = "SHA256SUMS.txt"
METADATA_NAME = "snapshot.json"
NOTES_NAME = "release-notes.md"
ASSETS_NAME = "assets"
SNAPSHOT_VERSION = 2
COPY_BUFFER_SIZE = 1024 * 1024
MANIFEST_LINE = re.compile(
    rb"(?P<digest>[0-9a-f]{64})  (?P<name>[A-Za-z0-9][A-Za-z0-9._+-]*)"
)


class SnapshotError(ValueError):
    pass


def _required_os_flag(name: str) -> int:
    value = getattr(os, name, None)
    if type(value) is not int or value == 0:
        raise SnapshotError(f"release input snapshot requires os.{name}")
    return value


def _regular_read_flags() -> int:
    return (
        os.O_RDONLY | _required_os_flag("O_NOFOLLOW") | _required_os_flag("O_NONBLOCK")
    )


def _directory_read_flags() -> int:
    try:
        return directory_open_flags()
    except SecurePathError as error:
        raise SnapshotError(str(error)) from error


@contextmanager
def _open_absolute_directory(path: Path) -> Iterator[int]:
    try:
        with secure_open_absolute_directory(path) as descriptor:
            yield descriptor
    except SecurePathError as error:
        raise SnapshotError(str(error)) from error


def _canonical_directory(path: Path) -> Path:
    try:
        return secure_canonical_directory(path)
    except SecurePathError as error:
        raise SnapshotError(str(error)) from error


def _canonical_child(path: Path) -> Path:
    try:
        return secure_canonical_child(path)
    except SecurePathError as error:
        raise SnapshotError(str(error)) from error


@contextmanager
def _open_regular_at(
    directory_descriptor: int,
    name: str,
    error_message: str,
) -> Iterator[BinaryIO]:
    try:
        descriptor = os.open(
            name,
            _regular_read_flags(),
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        raise SnapshotError(error_message) from error
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise SnapshotError(error_message)
        yield source


def _copy_stream_and_hash(source: BinaryIO, destination_path: Path) -> str:
    digest = hashlib.sha256()
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    destination_descriptor = os.open(destination_path, destination_flags, 0o600)
    try:
        with os.fdopen(destination_descriptor, "wb") as destination:
            destination_descriptor = -1
            while chunk := source.read(COPY_BUFFER_SIZE):
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
    finally:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
    destination_path.chmod(0o400)
    return digest.hexdigest()


def _copy_absolute_and_hash(source_path: Path, destination_path: Path) -> str:
    with _open_absolute_directory(source_path.parent) as parent_descriptor:
        with _open_regular_at(
            parent_descriptor,
            source_path.name,
            f"invalid release input '{source_path}': expected regular file",
        ) as source:
            return _copy_stream_and_hash(source, destination_path)


def _workspace() -> tuple[Path, Path]:
    raw_workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if not raw_workspace:
        raise SnapshotError("invalid GITHUB_WORKSPACE '': expected nonempty directory")
    lexical_workspace = Path(os.path.abspath(raw_workspace))
    workspace = lexical_workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise SnapshotError(
            f"invalid GITHUB_WORKSPACE '{raw_workspace}': expected directory"
        )
    return lexical_workspace, workspace


def _resolve_confined(raw_path: str, label: str, expected_kind: str) -> Path:
    if not raw_path:
        raise SnapshotError(f"invalid {label} '': expected nonempty path")
    lexical_workspace, workspace = _workspace()
    path = Path(raw_path)
    lexical = Path(os.path.abspath(path if path.is_absolute() else Path.cwd() / path))
    relative: Path | None = None
    boundary: Path | None = None
    for candidate in (lexical_workspace, workspace):
        try:
            relative = lexical.relative_to(candidate)
            boundary = candidate
            break
        except ValueError:
            continue
    if relative is None or boundary is None:
        raise SnapshotError(
            f"invalid {label} '{raw_path}': path escapes GITHUB_WORKSPACE"
        )

    current = boundary
    for component in relative.parts:
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as error:
            raise SnapshotError(
                f"invalid {label} '{raw_path}': path does not exist"
            ) from error
        if stat.S_ISLNK(mode):
            raise SnapshotError(
                f"invalid {label} '{raw_path}': symbolic links are not allowed"
            )

    resolved = workspace / relative
    try:
        resolved.relative_to(workspace)
    except ValueError as error:
        raise SnapshotError(
            f"invalid {label} '{raw_path}': path escapes GITHUB_WORKSPACE"
        ) from error
    if expected_kind == "directory" and not resolved.is_dir():
        raise SnapshotError(f"invalid {label} '{raw_path}': expected directory")
    if expected_kind == "file" and not resolved.is_file():
        raise SnapshotError(f"invalid {label} '{raw_path}': expected regular file")
    if not os.access(resolved, os.R_OK):
        raise SnapshotError(f"invalid {label} '{raw_path}': path is not readable")
    return resolved


def _read_manifest(
    source_dir: Path,
    source_descriptor: int,
) -> tuple[bytes, dict[str, str]]:
    with _open_regular_at(
        source_descriptor,
        MANIFEST_NAME,
        f"invalid dist_dir '{source_dir}': missing regular {MANIFEST_NAME}",
    ) as manifest:
        manifest_bytes = manifest.read()
    entries: dict[str, str] = {}
    for line_number, line in enumerate(manifest_bytes.splitlines(), start=1):
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise SnapshotError(
                f"invalid {MANIFEST_NAME} line {line_number}: expected SHA-256 and basename"
            )
        name = match.group("name").decode("ascii")
        if name == MANIFEST_NAME or name in entries:
            raise SnapshotError(
                f"invalid {MANIFEST_NAME} line {line_number}: duplicate or self entry '{name}'"
            )
        entries[name] = match.group("digest").decode("ascii")
    if not entries:
        raise SnapshotError(f"invalid {MANIFEST_NAME}: expected at least one asset")
    return manifest_bytes, entries


def _validate_inventory(
    source_dir: Path,
    source_descriptor: int,
    manifest_entries: dict[str, str],
) -> None:
    actual_names: set[str] = set()
    with os.scandir(source_descriptor) as entries:
        for entry in entries:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise SnapshotError(
                    f"invalid release asset '{source_dir / entry.name}': "
                    "expected readable regular file"
                )
            actual_names.add(entry.name)
    expected_names = set(manifest_entries) | {MANIFEST_NAME}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SnapshotError(
            f"invalid release asset inventory: missing={missing}, extra={extra}"
        )


def _write_bytes_exclusive(path: Path, payload: bytes) -> str:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(payload)
        destination.flush()
        os.fsync(destination.fileno())
    path.chmod(0o400)
    return hashlib.sha256(payload).hexdigest()


def _remove_directory_contents(directory_descriptor: int) -> None:
    os.fchmod(directory_descriptor, 0o700)
    with os.scandir(directory_descriptor) as entries:
        for entry in entries:
            if entry.is_symlink():
                raise SnapshotError("invalid release snapshot cleanup symlink")
            if entry.is_dir(follow_symlinks=False):
                child_descriptor = os.open(
                    entry.name,
                    _directory_read_flags(),
                    dir_fd=directory_descriptor,
                )
                try:
                    _remove_directory_contents(child_descriptor)
                finally:
                    os.close(child_descriptor)
                os.rmdir(entry.name, dir_fd=directory_descriptor)
            elif entry.is_file(follow_symlinks=False):
                os.unlink(entry.name, dir_fd=directory_descriptor)
            else:
                raise SnapshotError("invalid release snapshot cleanup entry")


def _remove_tree_at(parent_descriptor: int, root_name: str) -> None:
    root_descriptor = os.open(
        root_name,
        _directory_read_flags(),
        dir_fd=parent_descriptor,
    )
    try:
        root_identity = os.fstat(root_descriptor)
        _remove_directory_contents(root_descriptor)
        current_identity = os.stat(
            root_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            current_identity.st_dev != root_identity.st_dev
            or current_identity.st_ino != root_identity.st_ino
        ):
            raise SnapshotError("release snapshot root changed during cleanup")
    finally:
        os.close(root_descriptor)
    os.rmdir(root_name, dir_fd=parent_descriptor)


def _remove_tree(stage_parent: Path, stage_root: Path) -> None:
    if stage_root.parent != stage_parent:
        raise SnapshotError("invalid release snapshot cleanup boundary")
    with _open_absolute_directory(stage_parent) as parent_descriptor:
        _remove_tree_at(parent_descriptor, stage_root.name)


def _stage(source_raw: str, notes_raw: str, stage_parent_raw: str) -> Path:
    _regular_read_flags()
    source_dir = _resolve_confined(source_raw, "dist_dir", "directory")
    notes_path = (
        _resolve_confined(notes_raw, "notes_file", "file") if notes_raw else None
    )

    stage_parent_path = Path(os.path.abspath(stage_parent_raw))
    if stage_parent_path.is_symlink():
        raise SnapshotError(
            f"invalid RUNNER_TEMP '{stage_parent_raw}': symbolic links are not allowed"
        )
    try:
        stage_parent = _canonical_directory(stage_parent_path)
    except SnapshotError as error:
        raise SnapshotError(
            f"invalid RUNNER_TEMP '{stage_parent_raw}': expected regular directory"
        ) from error
    with _open_absolute_directory(source_dir) as source_descriptor:
        manifest_bytes, manifest_entries = _read_manifest(
            source_dir,
            source_descriptor,
        )
        _validate_inventory(source_dir, source_descriptor, manifest_entries)
        created_root = Path(
            tempfile.mkdtemp(prefix="justdocs-release-", dir=stage_parent)
        )
        stage_root = created_root
        try:
            if stage_root.parent != stage_parent:
                raise SnapshotError("invalid release snapshot creation boundary")
            assets_dir = stage_root / ASSETS_NAME
            assets_dir.mkdir(mode=0o700)
            metadata: dict[str, object] = {
                "version": SNAPSHOT_VERSION,
                "root_name": stage_root.name,
                "assets": {},
                "notes": None,
            }
            staged_assets = metadata["assets"]
            if not isinstance(staged_assets, dict):
                raise SnapshotError("invalid snapshot metadata construction")
            for name, expected_digest in sorted(manifest_entries.items()):
                with _open_regular_at(
                    source_descriptor,
                    name,
                    f"invalid release input '{source_dir / name}': "
                    "expected regular file",
                ) as source:
                    actual_digest = _copy_stream_and_hash(
                        source,
                        assets_dir / name,
                    )
                if actual_digest != expected_digest:
                    raise SnapshotError(
                        f"release asset checksum mismatch for '{name}': "
                        f"expected {expected_digest}, got {actual_digest}"
                    )
                staged_assets[name] = actual_digest
            staged_assets[MANIFEST_NAME] = _write_bytes_exclusive(
                assets_dir / MANIFEST_NAME, manifest_bytes
            )
            if notes_path is not None:
                metadata["notes"] = _copy_absolute_and_hash(
                    notes_path,
                    stage_root / NOTES_NAME,
                )
            metadata_payload = (
                json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _write_bytes_exclusive(stage_root / METADATA_NAME, metadata_payload)
            assets_dir.chmod(0o500)
            return stage_root
        except Exception as staging_error:
            try:
                _remove_tree(stage_parent, stage_root)
            except Exception as cleanup_error:
                raise SnapshotError(
                    f"release snapshot staging failed: {staging_error}; "
                    f"partial cleanup failed: {cleanup_error}"
                ) from staging_error
            raise


def _parse_metadata(metadata_bytes: bytes) -> dict[str, object]:
    metadata = json.loads(metadata_bytes.decode("utf-8"))
    if not isinstance(metadata, dict) or set(metadata) != {
        "version",
        "root_name",
        "assets",
        "notes",
    }:
        raise SnapshotError("invalid release snapshot metadata shape")
    if type(metadata["version"]) is not int or metadata["version"] != SNAPSHOT_VERSION:
        raise SnapshotError("invalid release snapshot metadata version")
    if not isinstance(metadata["root_name"], str):
        raise SnapshotError("invalid release snapshot root identity")
    if not isinstance(metadata["assets"], dict) or not metadata["assets"]:
        raise SnapshotError("invalid release snapshot asset metadata")
    if metadata["notes"] is not None and not isinstance(metadata["notes"], str):
        raise SnapshotError("invalid release snapshot notes metadata")
    return metadata


def _verify(stage_root_raw: str) -> None:
    _regular_read_flags()
    stage_root = _canonical_child(Path(stage_root_raw))
    if not stage_root.name.startswith("justdocs-release-"):
        raise SnapshotError("invalid release snapshot root")
    try:
        with _open_absolute_directory(stage_root.parent) as parent_descriptor:
            root_descriptor = os.open(
                stage_root.name,
                _directory_read_flags(),
                dir_fd=parent_descriptor,
            )
            try:
                with _open_regular_at(
                    root_descriptor,
                    METADATA_NAME,
                    f"invalid release snapshot: missing {METADATA_NAME}",
                ) as metadata_file:
                    metadata = _parse_metadata(metadata_file.read())
                if metadata["root_name"] != stage_root.name:
                    raise SnapshotError("invalid release snapshot root identity")
                assets = metadata["assets"]
                if not isinstance(assets, dict):
                    raise SnapshotError("invalid release snapshot asset metadata")
                if any(
                    not isinstance(name, str)
                    or not isinstance(digest, str)
                    or MANIFEST_LINE.fullmatch(
                        f"{digest}  {name}".encode("ascii", "strict")
                    )
                    is None
                    for name, digest in assets.items()
                ):
                    raise SnapshotError("invalid release snapshot asset metadata")

                assets_descriptor = os.open(
                    ASSETS_NAME,
                    _directory_read_flags(),
                    dir_fd=root_descriptor,
                )
                try:
                    with os.scandir(assets_descriptor) as asset_entries:
                        actual_names = {entry.name for entry in asset_entries}
                    if actual_names != set(assets):
                        raise SnapshotError("invalid release snapshot asset inventory")
                    for name, expected_digest in sorted(assets.items()):
                        digest = hashlib.sha256()
                        with _open_regular_at(
                            assets_descriptor,
                            name,
                            f"invalid release snapshot asset '{name}'",
                        ) as asset_file:
                            while chunk := asset_file.read(COPY_BUFFER_SIZE):
                                digest.update(chunk)
                        actual_digest = digest.hexdigest()
                        if actual_digest != expected_digest:
                            raise SnapshotError(
                                f"release snapshot checksum mismatch for '{name}': "
                                f"expected {expected_digest}, got {actual_digest}"
                            )
                finally:
                    os.close(assets_descriptor)

                expected_root_names = {ASSETS_NAME, METADATA_NAME}
                notes_digest = metadata["notes"]
                if isinstance(notes_digest, str):
                    expected_root_names.add(NOTES_NAME)
                    digest = hashlib.sha256()
                    with _open_regular_at(
                        root_descriptor,
                        NOTES_NAME,
                        "invalid release snapshot notes file",
                    ) as notes_file:
                        while chunk := notes_file.read(COPY_BUFFER_SIZE):
                            digest.update(chunk)
                    if digest.hexdigest() != notes_digest:
                        raise SnapshotError("release snapshot notes checksum mismatch")
                with os.scandir(root_descriptor) as root_entries:
                    if {entry.name for entry in root_entries} != expected_root_names:
                        raise SnapshotError("invalid release snapshot root inventory")
            finally:
                os.close(root_descriptor)
    except OSError as error:
        raise SnapshotError("invalid release snapshot path") from error


def _cleanup(stage_root_raw: str, stage_parent_raw: str) -> None:
    stage_root = _canonical_child(Path(stage_root_raw))
    stage_parent = _canonical_directory(Path(os.path.abspath(stage_parent_raw)))
    if stage_root.parent != stage_parent or not stage_root.name.startswith(
        "justdocs-release-"
    ):
        raise SnapshotError("invalid release snapshot cleanup boundary")
    try:
        with _open_absolute_directory(stage_parent) as parent_descriptor:
            _remove_tree_at(parent_descriptor, stage_root.name)
    except OSError as error:
        raise SnapshotError("invalid release snapshot cleanup path") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("source_dir")
    stage_parser.add_argument("notes_file")
    stage_parser.add_argument("stage_parent")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("stage_root")
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("stage_root")
    cleanup_parser.add_argument("stage_parent")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "stage":
            stage_root = _stage(
                arguments.source_dir,
                arguments.notes_file,
                arguments.stage_parent,
            )
            print(stage_root)
        elif arguments.command == "verify":
            _verify(arguments.stage_root)
        else:
            _cleanup(arguments.stage_root, arguments.stage_parent)
    except (SnapshotError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"release input snapshot failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
