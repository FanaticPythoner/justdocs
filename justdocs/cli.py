"""Expose justdocs command line helpers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from justdocs import project_recipes
from justdocs import self_update
from justdocs.paths import ThemeAssetError, theme_dir
from justdocs.project import ProjectJustfileConfig, ProjectJustfileError, write_project_justfile
from justdocs.project_recipes import (
    DEFAULT_ADDR,
    DEFAULT_EXTRA_PACKAGES,
    ProjectRecipeConfig,
    ProjectRecipeError,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the command parser."""

    parser = argparse.ArgumentParser(prog="justdocs")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("theme-dir", help="Print the bundled MkDocs theme package path.")
    version_parser = subparsers.add_parser("version", help="Print installed package version.")
    version_parser.add_argument("--check", action="store_true", help="Check for available package updates.")
    version_parser.add_argument("--json", action="store_true", help="Print machine-readable version output.")
    init_parser = subparsers.add_parser("init", help="Write a project-local Justfile.")
    _add_project_init_arguments(init_parser)
    project_parser = subparsers.add_parser(
        "project",
        aliases=("projects",),
        help="Run project Justfile recipe equivalents.",
    )
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_init_parser = project_subparsers.add_parser("init", help="Write a project-local Justfile.")
    _add_project_init_arguments(project_init_parser)
    for command in ("install", "check", "build", "serve", "serve-clean", "free-port", "clean", "dist-clean"):
        command_parser = project_subparsers.add_parser(command, help=f"Run the project {command} recipe.")
        _add_project_recipe_arguments(command_parser)
    self_parser = subparsers.add_parser("self", help="Manage the installed justdocs command.")
    self_subparsers = self_parser.add_subparsers(dest="self_command", required=True)
    check_parser = self_subparsers.add_parser("check-update", help="Check PyPI and GitHub releases.")
    check_parser.add_argument("--json", action="store_true", help="Print machine-readable update output.")
    check_parser.add_argument("--timeout", type=float, default=self_update.DEFAULT_TIMEOUT_SECONDS, help="Network timeout in seconds.")
    check_parser.add_argument(
        "--source",
        action="append",
        choices=("pypi", "github"),
        help="Update metadata source. May be repeated.",
    )
    update_parser = self_subparsers.add_parser("update", help="Upgrade the installed package.")
    update_parser.add_argument("--version", default="latest", help="Version to install, or latest.")
    update_parser.add_argument("--source", choices=("pypi", "github"), default="pypi", help="Package source.")
    update_parser.add_argument("--user", action="store_true", help="Install into the Python user site.")
    update_parser.add_argument("--timeout", type=float, default=self_update.DEFAULT_TIMEOUT_SECONDS, help="Network timeout in seconds.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface."""

    parser = build_parser()
    if argv is not None and len(argv) == 0:
        return _print_default_help(parser)
    if argv is None and len(sys.argv) == 1:
        return _print_default_help(parser)
    args = parser.parse_args(argv)
    if args.command == "theme-dir":
        try:
            print(theme_dir())
        except ThemeAssetError as error:
            parser.exit(1, f"{error}\n")
        return 0
    if args.command == "version":
        return _print_version(parser, args)
    if args.command == "init":
        return _write_project_justfile(parser, args)
    if hasattr(args, "project_command"):
        if args.project_command == "init":
            return _write_project_justfile(parser, args)
        try:
            _run_project_recipe(args)
        except (ProjectRecipeError, ProjectJustfileError) as error:
            parser.exit(1, f"{error}\n")
        return 0
    if hasattr(args, "self_command"):
        return _run_self_command(parser, args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _print_default_help(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    print()
    print("Common commands:")
    print("  justdocs project init --root docs-project")
    print("  justdocs project check --root docs-project")
    print("  justdocs self check-update")
    print("  justdocs self update")
    return 0


def _print_version(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    current = self_update.installed_version()
    if not args.check:
        if args.json:
            print(json.dumps({"version": current}, sort_keys=True))
        else:
            print(current)
        return 0
    try:
        result = self_update.check_update()
    except self_update.UpdateCheckError as error:
        parser.exit(1, f"{error}\n")
    if args.json:
        print(json.dumps(self_update.result_payload(result), sort_keys=True))
        return 0
    _print_update_result(result)
    return 0


def _write_project_justfile(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    config = ProjectJustfileConfig(
        root=Path(args.root),
        mkdocs_config=args.mkdocs_config,
        addr=args.addr,
        package=args.package,
    )
    try:
        print(write_project_justfile(config, force=args.force))
    except ProjectJustfileError as error:
        parser.exit(1, f"{error}\n")
    return 0


def _run_project_recipe(args: argparse.Namespace) -> None:
    config = ProjectRecipeConfig(
        root=Path(args.root),
        mkdocs_config=args.mkdocs_config,
        addr=args.addr,
        port=args.port,
        package=args.package,
        extra_packages=args.extra_packages,
        venv=Path(args.venv),
        python=args.python,
    )
    recipes = {
        "install": project_recipes.install,
        "check": project_recipes.check,
        "build": project_recipes.build,
        "serve": project_recipes.serve,
        "serve-clean": project_recipes.serve_clean,
        "free-port": project_recipes.free_port,
        "clean": project_recipes.clean,
        "dist-clean": project_recipes.dist_clean,
    }
    recipes[args.project_command](config)


def _run_self_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.self_command == "check-update":
        sources = tuple(args.source) if args.source else ("pypi", "github")
        try:
            result = self_update.check_update(timeout=args.timeout, sources=sources)
        except self_update.UpdateCheckError as error:
            parser.exit(1, f"{error}\n")
        if args.json:
            print(json.dumps(self_update.result_payload(result), sort_keys=True))
        else:
            _print_update_result(result)
        return 0
    if args.self_command == "update":
        try:
            self_update.update_package(
                version=args.version,
                source=args.source,
                user=args.user,
                timeout=args.timeout,
            )
        except (self_update.UpdateCheckError, self_update.UpdateInstallError) as error:
            parser.exit(1, f"{error}\n")
        print(f"updated {self_update.PACKAGE_NAME}")
        return 0
    parser.error(f"unknown self command: {args.self_command}")
    return 2


def _print_update_result(result: self_update.UpdateCheckResult) -> None:
    print(f"current: {result.current_version}")
    if result.latest is None:
        print("latest: current")
    else:
        print(f"latest: {result.latest.version}")
        print(f"source: {result.latest.source}")
        print(f"url: {result.latest.url}")
        print(f"command: justdocs self update --source {result.latest.source} --version {result.latest.version}")
    for error in result.errors:
        print(f"warning: {error}", file=sys.stderr)


def _add_project_init_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Project root path.")
    parser.add_argument(
        "--mkdocs-config",
        default=os.environ.get("JUSTDOCS_CONFIG", "mkdocs.yml"),
        help="MkDocs config path.",
    )
    parser.add_argument(
        "--addr",
        default=os.environ.get("JUSTDOCS_ADDR", DEFAULT_ADDR),
        help="MkDocs serve bind address.",
    )
    parser.add_argument(
        "--package",
        default=os.environ.get("JUSTDOCS_PACKAGE", "justdocs"),
        help="Pip install spec for justdocs.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing Justfile.")


def _add_project_recipe_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Project root path.")
    parser.add_argument(
        "--mkdocs-config",
        default=os.environ.get("JUSTDOCS_CONFIG", "mkdocs.yml"),
        help="MkDocs config path.",
    )
    parser.add_argument(
        "--addr",
        default=os.environ.get("JUSTDOCS_ADDR", DEFAULT_ADDR),
        help="MkDocs serve bind address.",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("JUSTDOCS_PORT"),
        help="TCP port used by free-port and serve-clean.",
    )
    parser.add_argument(
        "--package",
        default=os.environ.get("JUSTDOCS_PACKAGE", "justdocs"),
        help="Pip install spec for justdocs.",
    )
    parser.add_argument(
        "--extra-packages",
        default=os.environ.get("JUSTDOCS_EXTRA_PACKAGES", DEFAULT_EXTRA_PACKAGES),
        help="Additional pip package specs.",
    )
    parser.add_argument(
        "--venv",
        default=os.environ.get("JUSTDOCS_VENV", ".venv"),
        help="Virtualenv directory.",
    )
    parser.add_argument(
        "--python",
        default=os.environ.get("JUSTDOCS_PYTHON", sys.executable),
        help="Python executable used to create the virtualenv.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
