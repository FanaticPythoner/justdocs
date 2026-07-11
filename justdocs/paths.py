"""Return filesystem paths for bundled MkDocs assets."""

from __future__ import annotations

from pathlib import Path


class ThemeAssetError(RuntimeError):
    """Report an incomplete bundled theme asset set."""


class TemplateAssetError(RuntimeError):
    """Report an incomplete bundled template asset set."""


PACKAGE_DIR = Path(__file__).resolve().parent
THEME_DIR = PACKAGE_DIR / "theme"
TEMPLATE_DIR = PACKAGE_DIR / "templates"

REQUIRED_THEME_FILES = (
    "404.html",
    "base.html",
    "mkdocs_theme.yml",
    "main.html",
    "__init__.py",
    "assets/css/highlightjs-copy.min.css",
    "assets/css/highlightjs.min.css",
    "assets/css/theme.css",
    "assets/js/highlightjs-copy.min.js",
    "assets/js/highlightjs.min.js",
    "assets/js/mermaid.LICENSE.txt",
    "assets/js/mermaid.min.js",
    "assets/js/theme.js",
)

REQUIRED_TEMPLATE_FILES = ("project.Justfile",)


def theme_dir() -> Path:
    """Return the absolute MkDocs theme package path."""

    missing = [
        path for path in REQUIRED_THEME_FILES if not (THEME_DIR / path).is_file()
    ]
    if missing:
        joined = ", ".join(missing)
        raise ThemeAssetError(f"justdocs theme incomplete: missing {joined}")
    return THEME_DIR


def project_justfile_template() -> Path:
    """Return the absolute project Justfile template path."""

    missing = [
        path for path in REQUIRED_TEMPLATE_FILES if not (TEMPLATE_DIR / path).is_file()
    ]
    if missing:
        joined = ", ".join(missing)
        raise TemplateAssetError(f"justdocs templates incomplete: missing {joined}")
    return TEMPLATE_DIR / "project.Justfile"
