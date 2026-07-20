"""Share source install locking and subprocess execution helpers."""

from __future__ import annotations

import contextlib
import hashlib
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO, Mapping


LOCK_ROOT = "justdocs-install-locks"
INTERRUPT_GRACE_SECONDS = 5.0
INTERRUPT_TERMINATE_SECONDS = 5.0
INTERRUPT_KILL_SECONDS = 5.0
PROCESS_WAIT_POLL_SECONDS = 0.025


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
        process_options: dict[str, object] = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            [str(part) for part in command],
            cwd=cwd,
            env=env,
            **process_options,
        )
    except OSError as error:
        raise error_type(
            f"command execution failed: {format_command(command)}: {error}"
        ) from error
    try:
        returncode = process.wait()
    except KeyboardInterrupt:
        _reap_interrupted_process(process)
        raise
    if returncode != 0:
        raise error_type(
            f"command failed with exit code {returncode}: {format_command(command)}",
        )


def _reap_interrupted_process(process: subprocess.Popen[bytes]) -> None:
    """Interrupt and reap one owned subprocess tree."""

    _signal_process_tree(process, signal.SIGINT)
    if _wait_process_tree(process, INTERRUPT_GRACE_SECONDS):
        return
    _signal_process_tree(process, signal.SIGTERM)
    if _wait_process_tree(process, INTERRUPT_TERMINATE_SECONDS):
        return
    _force_kill_process_tree(process)
    if not _wait_process_tree(process, INTERRUPT_KILL_SECONDS):
        raise InstallSupportError("interrupted command process tree remains active")


def _signal_process_tree(
    process: subprocess.Popen[bytes],
    signal_number: signal.Signals,
) -> None:
    """Send one signal to an owned subprocess tree."""

    try:
        if os.name == "nt":
            if signal_number == signal.SIGINT:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            elif signal_number == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
            return
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return
    except OSError as error:
        raise InstallSupportError(
            f"cannot signal command process tree {process.pid}: {error}"
        ) from error


def _force_kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Force termination of an owned subprocess tree."""

    if os.name != "nt":
        _signal_process_tree(process, signal.SIGKILL)
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    except OSError as error:
        raise InstallSupportError(
            f"cannot kill command process tree {process.pid}: {error}"
        ) from error


def _wait_process_tree(
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> bool:
    """Wait for an owned subprocess tree to terminate."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        process.poll()
        if process.returncode is not None and not _process_group_exists(process.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_WAIT_POLL_SECONDS, remaining))


def _process_group_exists(process_id: int) -> bool:
    """Return whether a POSIX process group remains active."""

    if os.name == "nt":
        return False
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
