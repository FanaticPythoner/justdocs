"""Install and remove the isolated justdocs command environment."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from justdocs.constants import PACKAGE_NAME
from justdocs.install_support import run_command


class GlobalCliError(RuntimeError):
    """Report invalid global command install state."""


def install(project_root: Path) -> Path:
    """Install the source package through the platform bootstrapper."""

    root = source_project_root(project_root)
    environment = bootstrap_environment("install", root)
    run_bootstrap(root, environment)
    return installed_command_path(environment)


def uninstall(project_root: Path) -> None:
    """Remove the isolated package through the platform bootstrapper."""

    root = source_project_root(project_root)
    run_bootstrap(root, bootstrap_environment("uninstall", root))


def bootstrap_environment(action: str, project_root: Path) -> dict[str, str]:
    """Return bootstrap process environment for a source-tree action."""

    environment = dict(os.environ)
    environment.update(
        {
            "JUSTDOCS_INSTALL_ACTION": action,
            "JUSTDOCS_INSTALL_SPEC": str(project_root),
            "JUSTDOCS_PYTHON": sys.executable,
        },
    )
    return environment


def run_bootstrap(project_root: Path, environment: Mapping[str, str]) -> None:
    """Run the platform bootstrap script from a source tree."""

    script = project_root / ("install.ps1" if os.name == "nt" else "install.sh")
    if not script.is_file():
        raise GlobalCliError(f"bootstrap script missing: {script}")
    if os.name == "nt":
        command = (
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        )
    else:
        command = ("sh", str(script))
    run_command(command, cwd=project_root, env=environment, error_type=GlobalCliError)


def installed_command_path(environment: Mapping[str, str]) -> Path:
    """Return the bootstrap-managed command path."""

    configured = environment.get("JUSTDOCS_INSTALL_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        local_app_data = environment.get("LOCALAPPDATA")
        if not local_app_data:
            raise GlobalCliError("LOCALAPPDATA missing: cannot resolve install root")
        root = (Path(local_app_data) / PACKAGE_NAME).resolve()
    else:
        home = environment.get("HOME")
        if not home:
            raise GlobalCliError("HOME missing: cannot resolve install root")
        root = (Path(home) / f".{PACKAGE_NAME}").resolve()
    suffix = "justdocs.exe" if os.name == "nt" else "justdocs"
    return root / "bin" / suffix


def build_parser() -> argparse.ArgumentParser:
    """Create the global command installer parser."""

    parser = argparse.ArgumentParser(prog="python -m justdocs.global_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("install", "Install justdocs in an isolated global command environment."),
        ("uninstall", "Remove the isolated global command environment."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument(
            "--project-root", default=".", help="Source project root path."
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the global command installer interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            install(Path(args.project_root))
            return 0
        if args.command == "uninstall":
            uninstall(Path(args.project_root))
            return 0
    except GlobalCliError as error:
        parser.exit(1, f"{error}\n")
    parser.error(f"unknown command: {args.command}")
    return 2


def source_project_root(project_root: Path) -> Path:
    """Return a validated source project root."""

    root = project_root.resolve()
    if not (root / "pyproject.toml").is_file():
        raise GlobalCliError(f"project root missing pyproject.toml: {root}")
    return root


if __name__ == "__main__":
    raise SystemExit(main())
