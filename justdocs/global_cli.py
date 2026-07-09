"""Install and remove the justdocs user-global console script."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

from justdocs.install_support import install_lock, run_command


PACKAGE_NAME = "justdocs"
CONSOLE_SCRIPT = "justdocs"


class GlobalCliError(RuntimeError):
    """Report invalid global console-script install state."""


def user_scripts_dir() -> Path:
    """Return the current interpreter user script directory."""

    scheme = f"{os.name}_user"
    try:
        path = sysconfig.get_path("scripts", scheme=scheme)
    except KeyError as error:
        raise GlobalCliError(f"missing Python user install scheme: {scheme}") from error
    if path is None:
        raise GlobalCliError(f"missing Python user script directory: {scheme}")
    return Path(path)


def console_script_candidates(scripts_dir: Path | None = None) -> tuple[Path, ...]:
    """Return platform-specific console script paths."""

    root = user_scripts_dir() if scripts_dir is None else scripts_dir
    if os.name == "nt":
        return (
            root / f"{CONSOLE_SCRIPT}.exe",
            root / f"{CONSOLE_SCRIPT}-script.py",
            root / CONSOLE_SCRIPT,
        )
    return (root / CONSOLE_SCRIPT,)


def existing_console_scripts(scripts_dir: Path | None = None) -> tuple[Path, ...]:
    """Return installed console script candidates."""

    return tuple(path for path in console_script_candidates(scripts_dir) if path.exists())


def install(project_root: Path) -> Path:
    """Install the package as a user-global console script."""

    root = _source_project_root(project_root)
    with install_lock(root):
        run_pip(("install", "--user", "--upgrade", str(root)))
    return verify_installed()


def uninstall() -> None:
    """Remove the package from the current interpreter environment."""

    run_pip(("uninstall", "--yes", PACKAGE_NAME))
    verify_uninstalled()


def verify_installed() -> Path:
    """Return the PATH-resolved console script after install."""

    scripts_dir = user_scripts_dir()
    installed = existing_console_scripts(scripts_dir)
    if not installed:
        raise GlobalCliError(f"global install failed: missing console script in {scripts_dir}")
    resolved = shutil.which(CONSOLE_SCRIPT)
    if resolved is None:
        raise GlobalCliError(f"global install failed: PATH missing {scripts_dir}")
    resolved_path = Path(resolved)
    if not any(_same_existing_path(resolved_path, path) for path in installed):
        expected = _format_paths(installed)
        raise GlobalCliError(f"global install failed: PATH resolves {resolved_path}; expected {expected}")
    return resolved_path


def verify_uninstalled() -> None:
    """Raise when user-script files remain after uninstall."""

    scripts_dir = user_scripts_dir()
    remaining = existing_console_scripts(scripts_dir)
    if remaining:
        raise GlobalCliError(f"global uninstall failed: remaining scripts: {_format_paths(remaining)}")


def run_pip(args: Sequence[str]) -> None:
    """Run pip with the current interpreter."""

    command = [sys.executable, "-m", "pip", *args]
    run_command(command, error_type=GlobalCliError)


def build_parser() -> argparse.ArgumentParser:
    """Create the global console-script command parser."""

    parser = argparse.ArgumentParser(prog="python -m justdocs.global_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser(
        "install",
        help="Install justdocs as a user-global console script.",
    )
    install_parser.add_argument("--project-root", default=".", help="Source project root path.")
    subparsers.add_parser("uninstall", help="Remove the user-global console script.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the global console-script command interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            command_path = install(Path(args.project_root))
            print(f"installed {command_path}")
            return 0
        if args.command == "uninstall":
            uninstall()
            print(f"uninstalled {PACKAGE_NAME}")
            return 0
    except GlobalCliError as error:
        parser.exit(1, f"{error}\n")
    parser.error(f"unknown command: {args.command}")
    return 2


def _source_project_root(project_root: Path) -> Path:
    root = project_root.resolve()
    if not (root / "pyproject.toml").is_file():
        raise GlobalCliError(f"project root missing pyproject.toml: {root}")
    return root


def _same_existing_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return _normalized_path(left) == _normalized_path(right)


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _format_paths(paths: Sequence[Path]) -> str:
    return ", ".join(str(path) for path in paths)


if __name__ == "__main__":
    raise SystemExit(main())
