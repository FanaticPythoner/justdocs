"""Create project-local Justfiles for justdocs sites."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from justdocs.paths import TemplateAssetError, project_justfile_template


class ProjectJustfileError(RuntimeError):
    """Report invalid project Justfile generation state."""


class ProjectJustfileExistsError(ProjectJustfileError):
    """Report an existing project Justfile without overwrite permission."""


class ProjectJustfileInvalidPackageError(ProjectJustfileError):
    """Report a package spec rejected by project Justfile generation."""


@dataclass(frozen=True)
class ProjectJustfileConfig:
    """Store project Justfile generation inputs."""

    root: Path
    mkdocs_config: str = "mkdocs.yml"
    addr: str = "127.0.0.1:8000"
    package: str = "justdocs"

    @property
    def port(self) -> str:
        """Return the TCP port segment from the configured bind address."""

        return self.addr.rsplit(":", 1)[-1] if ":" in self.addr else self.addr


def render_project_justfile(config: ProjectJustfileConfig) -> str:
    """Render a project-local Justfile from packaged template assets."""

    _validate_package_spec(config.package)
    try:
        template = project_justfile_template().read_text(encoding="utf-8")
    except TemplateAssetError as error:
        raise ProjectJustfileError(str(error)) from error
    replacements = {
        "{{ mkdocs_config }}": config.mkdocs_config,
        "{{ addr }}": config.addr,
        "{{ port }}": config.port,
        "{{ package }}": config.package,
    }
    rendered = template
    for needle, value in replacements.items():
        rendered = rendered.replace(needle, value)
    return rendered


def write_project_justfile(config: ProjectJustfileConfig, *, force: bool = False) -> Path:
    """Write a project-local Justfile and return its absolute path."""

    root = config.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "Justfile"
    if path.exists() and not force:
        raise ProjectJustfileExistsError(f"project Justfile exists: {path}")
    path.write_text(render_project_justfile(config), encoding="utf-8")
    return path


def _validate_package_spec(package: str) -> None:
    """Reject package specs that select mutable development install mode."""

    try:
        tokens = shlex.split(package)
    except ValueError as error:
        raise ProjectJustfileInvalidPackageError(f"invalid package spec: {package}") from error
    if not tokens:
        raise ProjectJustfileInvalidPackageError("invalid package spec: empty")
    if any(token == "-e" or token == "--editable" or token.startswith("--editable=") for token in tokens):
        raise ProjectJustfileInvalidPackageError("invalid package spec: editable install flags rejected")
