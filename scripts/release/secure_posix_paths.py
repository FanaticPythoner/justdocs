from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SecurePathError(ValueError):
    """Report a violated descriptor-bound POSIX path invariant."""


def directory_open_flags() -> int:
    """Return flags that open a directory without following its final component."""

    flags = os.O_RDONLY
    for name in ("O_DIRECTORY", "O_NOFOLLOW"):
        value = getattr(os, name, None)
        if type(value) is not int or value == 0:
            raise SecurePathError(f"secure POSIX paths require os.{name}")
        flags |= value
    return flags


@contextmanager
def open_absolute_directory(path: Path) -> Iterator[int]:
    """Open every absolute directory component relative to its parent descriptor."""

    if not path.is_absolute() or ".." in path.parts:
        raise SecurePathError(f"invalid absolute directory path '{path}'")
    try:
        descriptor = os.open(path.anchor, directory_open_flags())
    except OSError as error:
        raise SecurePathError(f"invalid absolute directory path '{path}'") from error
    try:
        for component in path.parts[1:]:
            try:
                child_descriptor = os.open(
                    component,
                    directory_open_flags(),
                    dir_fd=descriptor,
                )
            except OSError as error:
                raise SecurePathError(
                    f"invalid absolute directory path '{path}'"
                ) from error
            os.close(descriptor)
            descriptor = child_descriptor
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _system_alias_target(path: Path) -> tuple[Path, tuple[int, ...]] | None:
    try:
        root_descriptor = os.open(path.anchor, directory_open_flags())
    except OSError as error:
        raise SecurePathError(f"invalid absolute directory path '{path}'") from error
    try:
        root_metadata = os.fstat(root_descriptor)
        first_component = path.parts[1]
        before = os.stat(
            first_component,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISLNK(before.st_mode):
            return None
        if (
            root_metadata.st_uid != 0
            or root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or before.st_uid != 0
        ):
            raise SecurePathError(
                f"untrusted first-component symbolic link in directory path '{path}'"
            )
        target = os.readlink(first_component, dir_fd=root_descriptor)
        after = os.stat(
            first_component,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise SecurePathError(f"invalid absolute directory path '{path}'") from error
    finally:
        os.close(root_descriptor)
    identity = _identity(before)
    if _identity(after) != identity:
        raise SecurePathError(
            f"first-component symbolic link changed in directory path '{path}'"
        )
    target_path = Path(
        os.path.abspath(
            target if os.path.isabs(target) else os.path.join(path.anchor, target)
        )
    )
    return target_path, identity


def _verify_system_alias(path: Path, identity: tuple[int, ...]) -> None:
    try:
        root_descriptor = os.open(path.anchor, directory_open_flags())
    except OSError as error:
        raise SecurePathError(f"invalid absolute directory path '{path}'") from error
    try:
        metadata = os.stat(
            path.parts[1],
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise SecurePathError(f"invalid absolute directory path '{path}'") from error
    finally:
        os.close(root_descriptor)
    if _identity(metadata) != identity:
        raise SecurePathError(
            f"first-component symbolic link changed in directory path '{path}'"
        )


def canonical_directory(path: Path) -> Path:
    """Return an absolute directory path with one trusted system alias expanded."""

    if not path.is_absolute() or ".." in path.parts:
        raise SecurePathError(f"invalid absolute directory path '{path}'")
    if len(path.parts) == 1:
        canonical = path
        alias_identity = None
    else:
        alias = _system_alias_target(path)
        if alias is None:
            canonical = path
            alias_identity = None
        else:
            target, alias_identity = alias
            canonical = target.joinpath(*path.parts[2:])
    with open_absolute_directory(canonical):
        pass
    if alias_identity is not None:
        _verify_system_alias(path, alias_identity)
    return canonical


def canonical_child(raw_path: str | Path) -> Path:
    """Return an absolute child path with its parent securely canonicalized."""

    absolute = Path(os.path.abspath(raw_path))
    if not absolute.name:
        raise SecurePathError(f"invalid absolute child path '{raw_path}'")
    return canonical_directory(absolute.parent) / absolute.name
