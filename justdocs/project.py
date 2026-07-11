"""Create project-local Justfiles for justdocs sites."""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from justdocs.constants import DEFAULT_ADDR, DEFAULT_EXTRA_PACKAGES, PACKAGE_NAME
from justdocs.paths import TemplateAssetError, project_justfile_template


PROJECT_CONFIG_PREFIX = "# justdocs-config: "
PROJECT_CONFIG_SCHEMA = 1
MAX_PROJECT_CONFIG_BYTES = 64 * 1024


class ProjectJustfileError(RuntimeError):
    """Report invalid project Justfile generation state."""


class ProjectJustfileExistsError(ProjectJustfileError):
    """Report an existing project Justfile without overwrite permission."""


class ProjectJustfileInvalidPackageError(ProjectJustfileError):
    """Report a package spec rejected by project Justfile generation."""


class ProjectJustfileWriteError(ProjectJustfileError):
    """Report a project Justfile filesystem mutation failure."""


@dataclass(frozen=True)
class ProjectJustfileConfig:
    """Store project Justfile generation inputs."""

    root: Path
    mkdocs_config: str = "mkdocs.yml"
    addr: str = DEFAULT_ADDR
    package: str = PACKAGE_NAME
    extra_packages: str = DEFAULT_EXTRA_PACKAGES
    venv: str = ".venv"


def render_project_justfile(config: ProjectJustfileConfig) -> str:
    """Render a project-local Justfile from packaged template assets."""

    _validate_project_config(config)
    try:
        template = project_justfile_template().read_text(encoding="utf-8")
    except (TemplateAssetError, OSError) as error:
        raise ProjectJustfileError(str(error)) from error
    payload = {
        "addr": config.addr,
        "extra_packages": config.extra_packages,
        "mkdocs_config": config.mkdocs_config,
        "package": config.package,
        "schema": PROJECT_CONFIG_SCHEMA,
        "venv": config.venv,
    }
    marker = "{{ config_json }}"
    if template.count(marker) != 1:
        raise ProjectJustfileError(
            f"project Justfile template marker count invalid: {marker}"
        )
    config_json = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return template.replace(marker, config_json)


def read_project_justfile_config(root: Path) -> ProjectJustfileConfig:
    """Return project settings stored in a generated Justfile."""

    resolved_root = root.resolve()
    path = resolved_root / "Justfile"
    if not path.exists() and not path.is_symlink():
        return ProjectJustfileConfig(root=resolved_root)
    if path.is_symlink() or not path.is_file():
        raise ProjectJustfileError(
            f"project Justfile target is not a regular file: {path}"
        )
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(MAX_PROJECT_CONFIG_BYTES + 1)
    except OSError as error:
        raise ProjectJustfileError(
            f"cannot read project Justfile {path}: {error}"
        ) from error
    if len(first_line) > MAX_PROJECT_CONFIG_BYTES:
        raise ProjectJustfileError(
            f"project Justfile configuration exceeds {MAX_PROJECT_CONFIG_BYTES} bytes: {path}",
        )
    try:
        line = first_line.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as error:
        raise ProjectJustfileError(
            f"project Justfile configuration is not UTF-8: {path}"
        ) from error
    if not line.startswith(PROJECT_CONFIG_PREFIX):
        return ProjectJustfileConfig(root=resolved_root)
    try:
        payload = json.loads(line.removeprefix(PROJECT_CONFIG_PREFIX))
    except json.JSONDecodeError as error:
        raise ProjectJustfileError(
            f"project Justfile configuration is invalid JSON: {path}"
        ) from error
    return _project_config_from_payload(resolved_root, path, payload)


def _project_config_from_payload(
    root: Path, path: Path, payload: object
) -> ProjectJustfileConfig:
    """Return validated project settings from a decoded JSON value."""

    expected = {"schema", "mkdocs_config", "addr", "package", "extra_packages", "venv"}
    if not isinstance(payload, dict):
        raise ProjectJustfileError(
            f"project Justfile configuration must be an object: {path}"
        )
    fields = set(payload)
    if fields != expected:
        missing = sorted(expected - fields)
        unknown = sorted(fields - expected)
        raise ProjectJustfileError(
            f"project Justfile configuration fields invalid: missing={missing}, unknown={unknown}",
        )
    if type(payload["schema"]) is not int or payload["schema"] != PROJECT_CONFIG_SCHEMA:
        raise ProjectJustfileError(
            f"project Justfile configuration schema unsupported: {payload['schema']}",
        )
    string_fields = expected - {"schema"}
    invalid = sorted(
        field for field in string_fields if not isinstance(payload[field], str)
    )
    if invalid:
        raise ProjectJustfileError(
            f"project Justfile configuration strings required: {invalid}"
        )
    return ProjectJustfileConfig(
        root=root,
        mkdocs_config=payload["mkdocs_config"],
        addr=payload["addr"],
        package=payload["package"],
        extra_packages=payload["extra_packages"],
        venv=payload["venv"],
    )


def write_project_justfile(
    config: ProjectJustfileConfig, *, force: bool = False
) -> Path:
    """Write a project-local Justfile and return its absolute path."""

    rendered = render_project_justfile(config)
    root = config.root.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ProjectJustfileWriteError(
            f"cannot create project root {root}: {error}"
        ) from error
    path = root / "Justfile"
    exists = path.exists() or path.is_symlink()
    if exists and not force:
        raise ProjectJustfileExistsError(f"project Justfile exists: {path}")
    if exists and not path.is_file() and not path.is_symlink():
        raise ProjectJustfileWriteError(
            f"project Justfile target is not a file: {path}"
        )
    temporary: Path | None = None
    try:
        mode = (
            path.stat().st_mode & 0o777
            if path.is_file() and not path.is_symlink()
            else 0o644
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix=".Justfile.", dir=root)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError as cleanup_error:
                raise ProjectJustfileWriteError(
                    f"cannot write project Justfile {path}: {error}; "
                    f"cannot remove temporary file {temporary}: {cleanup_error}",
                ) from cleanup_error
        raise ProjectJustfileWriteError(
            f"cannot write project Justfile {path}: {error}"
        ) from error
    return path


def split_package_spec(package: str) -> tuple[str, ...]:
    """Split a package spec into subprocess arguments."""

    value = package.strip()
    if not value:
        raise ProjectJustfileInvalidPackageError("invalid package spec: empty")
    if _is_pip_option(value):
        raise ProjectJustfileInvalidPackageError(
            f"invalid package spec: pip option rejected: {value}"
        )
    if _is_single_package_argument(value):
        return (value,)
    try:
        tokens = shlex.split(value)
    except ValueError as error:
        raise ProjectJustfileInvalidPackageError(
            f"invalid package spec: {package}"
        ) from error
    option = next((token for token in tokens if _is_pip_option(token)), None)
    if option is not None:
        raise ProjectJustfileInvalidPackageError(
            f"invalid package spec: pip option rejected: {option}"
        )
    return tuple(tokens)


def _validate_package_spec(package: str) -> None:
    """Reject package specs containing pip command options."""

    split_package_spec(package)


def _validate_project_config(config: ProjectJustfileConfig) -> None:
    """Validate generated project settings before filesystem mutation."""

    for name, value in (
        ("mkdocs config", config.mkdocs_config),
        ("address", config.addr),
        ("venv", config.venv),
    ):
        if not value.strip():
            raise ProjectJustfileError(f"invalid project {name}: empty")
    _validate_package_spec(config.package)
    if config.extra_packages.strip():
        _validate_package_spec(config.extra_packages)


def _is_pip_option(value: str) -> bool:
    """Return whether a package token selects pip command behavior."""

    return value.startswith("-")


def _is_single_package_argument(value: str) -> bool:
    """Return whether text is one requirement, URL, or filesystem path."""

    try:
        Requirement(value)
    except InvalidRequirement:
        return bool(
            value.startswith((".", "/", "~", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", value)
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value)
        )
    return True
