from __future__ import annotations

import errno
import importlib
import os
import select
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from justdocs import install_support, project_recipes
from justdocs.project import ProjectJustfileConfig, write_project_justfile
from justdocs.project_recipes import ProjectRecipeConfig, ProjectRecipeError

PTY = importlib.import_module("pty") if os.name == "posix" else None


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_SECONDS = 90.0
EXIT_TIMEOUT_SECONDS = 15.0
PROCESS_EXIT_POLL_SECONDS = 0.025


def _unused_loopback_port() -> int:
    """Return one kernel-selected loopback TCP port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _read_pty(master_fd: int) -> tuple[bytes, bool]:
    """Read available PTY bytes and report terminal closure."""

    chunks: list[bytes] = []
    closed = False
    while True:
        try:
            chunk = os.read(master_fd, 65_536)
        except BlockingIOError:
            break
        except OSError as error:
            if error.errno != errno.EIO:
                raise
            closed = True
            break
        if not chunk:
            closed = True
            break
        chunks.append(chunk)
    return b"".join(chunks), closed


def _port_is_bound(port: int) -> bool:
    """Return whether the loopback TCP port accepts connections."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_port(port: int, *, bound: bool, timeout_seconds: float) -> None:
    """Wait until the loopback TCP port reaches the requested state."""

    deadline = time.monotonic() + timeout_seconds
    while _port_is_bound(port) is not bound:
        if time.monotonic() >= deadline:
            state = "bound" if bound else "free"
            raise AssertionError(f"TCP port {port} did not become {state}")
        time.sleep(PROCESS_EXIT_POLL_SECONDS)


def _process_parent_map() -> dict[int, int]:
    """Return the POSIX process parent relation."""

    completed = subprocess.run(
        ("ps", "-A", "-o", "pid=,ppid="),
        check=True,
        capture_output=True,
        text=True,
    )
    relations: dict[int, int] = {}
    for line in completed.stdout.splitlines():
        pid, parent_pid = (int(field) for field in line.split())
        relations[pid] = parent_pid
    return relations


def _descendant_process_ids(parent_pid: int) -> frozenset[int]:
    """Return all process ids descended from one POSIX process."""

    relations = _process_parent_map()
    descendants: set[int] = set()
    frontier = {parent_pid}
    while frontier:
        children = {
            pid for pid, owner in relations.items() if owner in frontier and pid not in descendants
        }
        descendants.update(children)
        frontier = children
    return frozenset(descendants)


def _wait_for_processes_to_exit(
    process_ids: frozenset[int], timeout_seconds: float
) -> None:
    """Wait until all selected POSIX process ids disappear."""

    deadline = time.monotonic() + timeout_seconds
    while remaining := process_ids.intersection(_process_parent_map()):
        if time.monotonic() >= deadline:
            rendered = ", ".join(str(pid) for pid in sorted(remaining))
            raise AssertionError(f"process ids remain active: {rendered}")
        time.sleep(PROCESS_EXIT_POLL_SECONDS)


def _project_command(root: Path, command: str, port: int) -> tuple[str, ...]:
    """Return one isolated project recipe command."""

    return (
        sys.executable,
        "-m",
        "justdocs.cli",
        "projects",
        command,
        "--root",
        str(root),
        "--addr",
        f"127.0.0.1:{port}",
        "--port",
        str(port),
        "--package",
        str(REPOSITORY_ROOT),
        "--extra-packages",
        "",
        "--venv",
        ".venv",
        "--python",
        sys.executable,
    )


def _create_project(directory: str, port: int) -> Path:
    """Create one project recipe fixture."""

    root = Path(directory) / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("# PTY fixture\n", encoding="utf-8")
    (root / "mkdocs.yml").write_text(
        "site_name: PTY fixture\ntheme:\n  name: justdocs\n",
        encoding="utf-8",
    )
    write_project_justfile(
        ProjectJustfileConfig(
            root=root,
            addr=f"127.0.0.1:{port}",
            package=str(REPOSITORY_ROOT),
            extra_packages="",
        )
    )
    return root


def _start_listener(root: Path, port: int) -> subprocess.Popen[bytes]:
    """Start one isolated loopback TCP listener."""

    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(root),
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _wait_for_port(port, bound=True, timeout_seconds=EXIT_TIMEOUT_SECONDS)
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    return process


def _reap_listener(process: subprocess.Popen[bytes]) -> None:
    """Reap one isolated loopback TCP listener."""

    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


class ProcessLifecycleTests(unittest.TestCase):
    """Verify bounded process termination state transitions."""

    def test_free_port_waits_for_listener_release(self) -> None:
        config = ProjectRecipeConfig(port="41001")
        with (
            patch.object(
                project_recipes,
                "bound_process_ids",
                side_effect=((101, 103), (103,), ()),
            ),
            patch.object(project_recipes, "terminate_process") as terminate_process,
            patch.object(project_recipes.time, "sleep") as sleep,
        ):
            project_recipes.free_port(config)
        self.assertEqual(
            [call(101), call(103), call(103)], terminate_process.call_args_list
        )
        self.assertEqual(2, sleep.call_count)

    def test_free_port_reports_listener_release_deadline(self) -> None:
        config = ProjectRecipeConfig(port="41002")
        with (
            patch.object(project_recipes, "FREE_PORT_RELEASE_SECONDS", -1.0),
            patch.object(
                project_recipes, "bound_process_ids", return_value=(107, 109)
            ),
            patch.object(project_recipes, "terminate_process"),
            self.assertRaisesRegex(
                ProjectRecipeError,
                "port 41002 remains bound by process ids: 107, 109",
            ),
        ):
            project_recipes.free_port(config)

    def test_interrupted_process_tree_escalates_in_order(self) -> None:
        process = Mock(pid=113)
        with (
            patch.object(install_support, "_signal_process_tree") as signal_tree,
            patch.object(install_support, "_force_kill_process_tree") as kill_tree,
            patch.object(
                install_support,
                "_wait_process_tree",
                side_effect=(False, False, True),
            ) as wait_tree,
        ):
            install_support._reap_interrupted_process(process)
        self.assertEqual(
            [
                call(process, signal.SIGINT),
                call(process, signal.SIGTERM),
            ],
            signal_tree.call_args_list,
        )
        kill_tree.assert_called_once_with(process)
        self.assertEqual(
            [
                call(process, install_support.INTERRUPT_GRACE_SECONDS),
                call(process, install_support.INTERRUPT_TERMINATE_SECONDS),
                call(process, install_support.INTERRUPT_KILL_SECONDS),
            ],
            wait_tree.call_args_list,
        )


@unittest.skipUnless(os.name == "posix", "PTY interruption requires POSIX")
class CliInterruptTests(unittest.TestCase):
    """Verify signal propagation and listener cleanup."""

    def _interrupt_server(self, command: str, *, occupy_port: bool = False) -> str:
        assert PTY is not None
        with TemporaryDirectory() as directory:
            port = _unused_loopback_port()
            root = _create_project(directory, port)
            listener = _start_listener(root, port) if occupy_port else None
            argv = _project_command(root, command, port)
            pid, master_fd = PTY.fork()
            if pid == 0:
                os.chdir(REPOSITORY_ROOT)
                os.execv(sys.executable, argv)
            os.set_blocking(master_fd, False)
            output = bytearray()
            status: int | None = None
            descendants: frozenset[int] = frozenset()
            try:
                startup_deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
                marker = f"Serving on http://127.0.0.1:{port}/".encode()
                while marker not in output:
                    if time.monotonic() >= startup_deadline:
                        self.fail("documentation server startup deadline expired")
                    select.select((master_fd,), (), (), 0.1)
                    chunk, closed = _read_pty(master_fd)
                    output.extend(chunk)
                    if closed:
                        self.fail("documentation server exited before readiness")
                descendants = _descendant_process_ids(pid)
                self.assertTrue(descendants)
                if listener is not None:
                    self.assertIsNotNone(listener.poll())
                os.write(master_fd, b"\x03")
                exit_deadline = time.monotonic() + EXIT_TIMEOUT_SECONDS
                while status is None:
                    child, observed = os.waitpid(pid, os.WNOHANG)
                    if child == pid:
                        status = observed
                        break
                    if time.monotonic() >= exit_deadline:
                        self.fail("documentation server exit deadline expired")
                    select.select((master_fd,), (), (), 0.1)
                    chunk, _closed = _read_pty(master_fd)
                    output.extend(chunk)
                chunk, _closed = _read_pty(master_fd)
                output.extend(chunk)
            finally:
                if status is None:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _child, status = os.waitpid(pid, 0)
                os.close(master_fd)
                if listener is not None:
                    _reap_listener(listener)
            rendered = output.decode("utf-8", errors="replace")
            self.assertEqual(130, os.waitstatus_to_exitcode(status))
            self.assertNotIn("Traceback (most recent call last)", rendered)
            self.assertIn("Shutting down", rendered)
            _wait_for_processes_to_exit(descendants, EXIT_TIMEOUT_SECONDS)
            _wait_for_port(port, bound=False, timeout_seconds=EXIT_TIMEOUT_SECONDS)
            return rendered

    def test_projects_serve_interrupt_exits_130_without_traceback(self) -> None:
        self._interrupt_server("serve")

    def test_projects_serve_clean_replaces_listener_and_exits_130(self) -> None:
        self._interrupt_server("serve-clean", occupy_port=True)

    def test_projects_free_port_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            port = _unused_loopback_port()
            root = _create_project(directory, port)
            listener = _start_listener(root, port)
            try:
                first = subprocess.run(
                    _project_command(root, "free-port", port),
                    cwd=REPOSITORY_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                second = subprocess.run(
                    _project_command(root, "free-port", port),
                    cwd=REPOSITORY_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                _reap_listener(listener)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertNotIn("Traceback (most recent call last)", first.stderr)
            self.assertNotIn("Traceback (most recent call last)", second.stderr)
            _wait_for_port(port, bound=False, timeout_seconds=EXIT_TIMEOUT_SECONDS)
