"""Run project recipes exposed by generated Justfiles."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from justdocs.install_support import install_lock, run_command
from justdocs.project import ProjectJustfileInvalidPackageError, split_package_spec


DEFAULT_ADDR = "127.0.0.1:8000"
DEFAULT_EXTRA_PACKAGES = "pymdown-extensions==10.12"


class ProjectRecipeError(RuntimeError):
    """Report invalid project recipe execution state."""


@dataclass(frozen=True)
class ProjectRecipeConfig:
    """Store project recipe execution inputs."""

    root: Path = Path(".")
    mkdocs_config: str = "mkdocs.yml"
    addr: str = DEFAULT_ADDR
    port: str | None = None
    package: str = "justdocs"
    extra_packages: str = DEFAULT_EXTRA_PACKAGES
    venv: Path = Path(".venv")
    python: str = sys.executable

    @property
    def resolved_root(self) -> Path:
        """Return the absolute project root."""

        return self.root.resolve()

    @property
    def resolved_venv(self) -> Path:
        """Return the absolute virtualenv path."""

        return _resolve_under_root(self.resolved_root, self.venv)

    @property
    def venv_python(self) -> Path:
        """Return the virtualenv Python executable path."""

        if os.name == "nt":
            return self.resolved_venv / "Scripts" / "python.exe"
        return self.resolved_venv / "bin" / "python"

    @property
    def port_value(self) -> str:
        """Return the configured or derived TCP port."""

        if self.port is not None:
            return self.port
        return self.addr.rsplit(":", 1)[-1] if ":" in self.addr else self.addr


def install(config: ProjectRecipeConfig) -> None:
    """Install project documentation dependencies."""

    root = _existing_root(config.resolved_root)
    _ensure_venv(config)
    run_pip(config, ("install", "--upgrade", "pip"))
    package_args = split_package_spec(config.package)
    extra_args = split_optional_package_spec(config.extra_packages)
    install_args = ("install", *package_args, *extra_args)
    source_root = local_source_root(package_args, root)
    if source_root is None:
        run_pip(config, install_args)
        return
    with install_lock(source_root):
        run_pip(config, install_args)


def check(config: ProjectRecipeConfig) -> None:
    """Build project documentation with strict MkDocs checks."""

    install(config)
    run_command(
        (
            str(config.venv_python),
            "-m",
            "mkdocs",
            "build",
            "-f",
            config.mkdocs_config,
            "--strict",
            "--clean",
        ),
        cwd=config.resolved_root,
        error_type=ProjectRecipeError,
    )


def build(config: ProjectRecipeConfig) -> None:
    """Build project documentation."""

    check(config)


def serve(config: ProjectRecipeConfig) -> None:
    """Serve project documentation."""

    install(config)
    run_command(
        (
            str(config.venv_python),
            "-m",
            "mkdocs",
            "serve",
            "-f",
            config.mkdocs_config,
            "-a",
            config.addr,
        ),
        cwd=config.resolved_root,
        error_type=ProjectRecipeError,
    )


def serve_clean(config: ProjectRecipeConfig) -> None:
    """Free the configured port and serve project documentation."""

    free_port(config)
    serve(config)


def free_port(config: ProjectRecipeConfig) -> None:
    """Terminate local processes bound to the configured TCP port."""

    port = validate_port(config.port_value)
    pids = bound_process_ids(port)
    for pid in pids:
        terminate_process(pid)


def clean(config: ProjectRecipeConfig) -> None:
    """Remove MkDocs output and cache directories."""

    root = _existing_root(config.resolved_root)
    for relative in ("site", ".cache", ".mkdocs_cache"):
        path = root / relative
        if path.exists():
            shutil.rmtree(path)


def dist_clean(config: ProjectRecipeConfig) -> None:
    """Remove MkDocs outputs, caches, and the configured virtualenv."""

    clean(config)
    venv_path = config.resolved_venv
    if venv_path.exists():
        shutil.rmtree(venv_path)


def run_pip(config: ProjectRecipeConfig, args: tuple[str, ...]) -> None:
    """Run pip from the project virtualenv."""

    run_command(
        (str(config.venv_python), "-m", "pip", *args),
        cwd=config.resolved_root,
        error_type=ProjectRecipeError,
    )


def split_optional_package_spec(package: str) -> tuple[str, ...]:
    """Return package arguments, or an empty tuple for blank input."""

    if package.strip() == "":
        return ()
    return split_package_spec(package)


def local_source_root(package_args: tuple[str, ...], cwd: Path) -> Path | None:
    """Return a local source package root when the package spec starts with one."""

    if not package_args:
        return None
    first = Path(package_args[0])
    candidate = first if first.is_absolute() else cwd / first
    if candidate.is_dir() and (candidate / "pyproject.toml").is_file():
        return candidate.resolve()
    return None


def validate_port(port: str) -> str:
    """Return a valid TCP port string."""

    try:
        value = int(port)
    except ValueError as error:
        raise ProjectRecipeError(f"invalid port {port}: expected 1..65535") from error
    if value < 1 or value > 65535:
        raise ProjectRecipeError(f"invalid port {port}: expected 1..65535")
    return str(value)


def bound_process_ids(port: str) -> tuple[int, ...]:
    """Return process ids bound to the given TCP port."""

    if os.name == "nt":
        return _windows_bound_process_ids(port)
    return _posix_bound_process_ids(port)


def terminate_process(pid: int) -> None:
    """Terminate a local process by id."""

    if os.name == "nt":
        run_command(("taskkill", "/PID", str(pid), "/F"), error_type=ProjectRecipeError)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError as error:
        raise ProjectRecipeError(f"cannot terminate process {pid}: permission denied") from error


def _ensure_venv(config: ProjectRecipeConfig) -> None:
    root = _existing_root(config.resolved_root)
    if config.venv_python.exists():
        return
    run_command(
        (config.python, "-m", "venv", str(config.resolved_venv)),
        cwd=root,
        error_type=ProjectRecipeError,
    )


def _existing_root(root: Path) -> Path:
    if not root.is_dir():
        raise ProjectRecipeError(f"project root missing: {root}")
    return root


def _resolve_under_root(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _posix_bound_process_ids(port: str) -> tuple[int, ...]:
    if shutil.which("lsof") is not None:
        completed = subprocess.run(
            ("lsof", "-tiTCP:" + port, "-sTCP:LISTEN"),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode not in (0, 1):
            raise ProjectRecipeError(f"lsof failed with exit code {completed.returncode}")
        return _parse_pid_lines(completed.stdout)
    if shutil.which("fuser") is not None:
        completed = subprocess.run(
            ("fuser", port + "/tcp"),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode not in (0, 1):
            raise ProjectRecipeError(f"fuser failed with exit code {completed.returncode}")
        return _parse_pid_lines(completed.stdout)
    raise ProjectRecipeError("free-port requires lsof or fuser")


def _windows_bound_process_ids(port: str) -> tuple[int, ...]:
    completed = subprocess.run(
        ("netstat", "-ano", "-p", "TCP"),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProjectRecipeError(f"netstat failed with exit code {completed.returncode}")
    pids: set[int] = set()
    suffix = ":" + port
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        local_address, state, pid = fields[1], fields[3], fields[4]
        if local_address.endswith(suffix) and state.upper() == "LISTENING":
            pids.add(int(pid))
    return tuple(sorted(pids))


def _parse_pid_lines(output: str) -> tuple[int, ...]:
    pids: set[int] = set()
    for token in output.split():
        if token.isdigit():
            pids.add(int(token))
    return tuple(sorted(pids))
