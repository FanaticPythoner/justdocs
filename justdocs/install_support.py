"""Share source install locking and subprocess execution helpers."""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO


LOCK_ROOT = "justdocs-install-locks"


class InstallSupportError(RuntimeError):
    """Report invalid install helper state."""


@contextlib.contextmanager
def install_lock(project_root: Path) -> Iterator[Path]:
    """Hold the per-source-tree install lock."""

    lock_dir = Path(tempfile.gettempdir()) / LOCK_ROOT
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:16]
    lock_path = lock_dir / f"{digest}.lock"
    with lock_path.open("a+b") as handle:
        _prepare_lock_byte(handle)
        _lock_file(handle)
        try:
            yield lock_path
        finally:
            _unlock_file(handle)


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    error_type: type[RuntimeError] = InstallSupportError,
) -> None:
    """Run a command and raise the configured error type on failure."""

    completed = subprocess.run([str(part) for part in command], cwd=cwd, check=False)
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
