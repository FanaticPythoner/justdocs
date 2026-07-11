"""Share source install locking and subprocess execution helpers."""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO, Mapping


LOCK_ROOT = "justdocs-install-locks"


class InstallSupportError(RuntimeError):
    """Report invalid install helper state."""


@contextlib.contextmanager
def install_lock(project_root: Path) -> Iterator[Path]:
    """Hold the per-source-tree install lock."""

    lock_dir = Path(tempfile.gettempdir()) / LOCK_ROOT
    try:
        lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not lock_dir.is_dir() or lock_dir.is_symlink():
            raise InstallSupportError(
                f"install lock root is not a directory: {lock_dir}"
            )
        if os.name != "nt":
            metadata = lock_dir.stat()
            if metadata.st_uid != os.getuid():
                raise InstallSupportError(
                    f"install lock root has another owner: {lock_dir}"
                )
            lock_dir.chmod(0o700)
    except OSError as error:
        raise InstallSupportError(
            f"cannot prepare install lock root {lock_dir}: {error}"
        ) from error
    canonical_root = os.path.normcase(str(project_root.expanduser().resolve()))
    digest = hashlib.sha256(canonical_root.encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{digest}.lock"
    try:
        if lock_path.is_symlink():
            raise InstallSupportError(f"install lock cannot be a symlink: {lock_path}")
        with lock_path.open("a+b") as handle:
            if os.name != "nt":
                lock_path.chmod(0o600)
            _prepare_lock_byte(handle)
            _lock_file(handle)
            try:
                yield lock_path
            finally:
                _unlock_file(handle)
    except OSError as error:
        raise InstallSupportError(
            f"cannot use install lock {lock_path}: {error}"
        ) from error


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    error_type: type[RuntimeError] = InstallSupportError,
) -> None:
    """Run a command and raise the configured error type on failure."""

    try:
        completed = subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            env=env,
            check=False,
        )
    except OSError as error:
        raise error_type(
            f"command execution failed: {format_command(command)}: {error}"
        ) from error
    if completed.returncode != 0:
        raise error_type(
            f"command failed with exit code {completed.returncode}: {format_command(command)}",
        )


def format_command(command: Sequence[str]) -> str:
    """Return a display command string."""

    return " ".join(str(part) for part in command)


def _prepare_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
