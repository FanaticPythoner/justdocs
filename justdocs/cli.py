"""Expose justdocs command line helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from justdocs.paths import ThemeAssetError, theme_dir
from justdocs.project import ProjectJustfileConfig, ProjectJustfileError, write_project_justfile


def build_parser() -> argparse.ArgumentParser:
    """Create the command parser."""

    parser = argparse.ArgumentParser(prog="justdocs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("theme-dir", help="Print the bundled MkDocs theme package path.")
    init_parser = subparsers.add_parser("init", help="Write a project-local Justfile.")
    init_parser.add_argument("--root", default=".", help="Project root path.")
    init_parser.add_argument("--mkdocs-config", default="mkdocs.yml", help="MkDocs config path.")
    init_parser.add_argument("--addr", default="127.0.0.1:8000", help="MkDocs serve bind address.")
    init_parser.add_argument("--package", default="justdocs", help="Pip install spec for justdocs.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing Justfile.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "theme-dir":
        try:
            print(theme_dir())
        except ThemeAssetError as error:
            parser.exit(1, f"{error}\n")
        return 0
    if args.command == "init":
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
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
