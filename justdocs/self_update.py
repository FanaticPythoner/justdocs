"""Check and update the installed justdocs package."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import PurePosixPath
from typing import Any, Protocol

from packaging.version import InvalidVersion, Version

from justdocs.install_support import run_command


PACKAGE_NAME = "justdocs"
DEFAULT_REPOSITORY = "FanaticPythoner/justdocs"
DEFAULT_TIMEOUT_SECONDS = 3.0
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
GITHUB_RELEASES_API = "https://api.github.com/repos/{repository}/releases/latest"


class UpdateCheckError(RuntimeError):
    """Report update metadata resolution failure."""


class UpdateInstallError(RuntimeError):
    """Report update installation failure."""


class JsonClient(Protocol):
    """Define JSON retrieval behavior."""

    def read_json(self, url: str, timeout: float) -> dict[str, Any]:
        """Return a JSON object from a URL."""


@dataclass(frozen=True)
class UpdateCandidate:
    """Store resolved update metadata."""

    source: str
    version: str
    url: str


@dataclass(frozen=True)
class UpdateCheckResult:
    """Store update check result."""

    current_version: str
    latest: UpdateCandidate | None
    errors: tuple[str, ...] = ()

    @property
    def update_available(self) -> bool:
        """Return whether a newer version exists."""

        return self.latest is not None


class UrlJsonClient:
    """Read JSON over HTTPS."""

    def read_json(self, url: str, timeout: float) -> dict[str, Any]:
        """Return a JSON object from a URL."""

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"{PACKAGE_NAME}/{installed_version()}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise UpdateCheckError(f"update check failed for {url}: {error}") from error
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise UpdateCheckError(f"update check failed for {url}: invalid JSON") from error
        if not isinstance(value, dict):
            raise UpdateCheckError(f"update check failed for {url}: JSON object expected")
        return value


def installed_version() -> str:
    """Return installed package version."""

    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        from justdocs import __version__

        return __version__


def check_update(
    *,
    client: JsonClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sources: tuple[str, ...] = ("pypi", "github"),
) -> UpdateCheckResult:
    """Return newest available version across enabled sources."""

    current = installed_version()
    reader = UrlJsonClient() if client is None else client
    enabled_sources = tuple(dict.fromkeys(sources))
    candidates: list[UpdateCandidate] = []
    errors: list[str] = []
    for source in enabled_sources:
        if source not in ("pypi", "github"):
            raise UpdateCheckError(f"unsupported update source: {source}")
        try:
            candidates.append(fetch_candidate(source, reader, timeout))
        except UpdateCheckError as error:
            errors.append(str(error))
    if not candidates:
        raise UpdateCheckError("; ".join(errors))
    latest = newest_candidate(candidates)
    if compare_versions(latest.version, current) <= 0:
        return UpdateCheckResult(current_version=current, latest=None, errors=tuple(errors))
    return UpdateCheckResult(current_version=current, latest=latest, errors=tuple(errors))


def fetch_candidate(source: str, client: JsonClient, timeout: float) -> UpdateCandidate:
    """Return update candidate for a source."""

    if source == "pypi":
        payload = client.read_json(PYPI_JSON_URL, timeout)
        info = payload.get("info")
        if not isinstance(info, dict):
            raise UpdateCheckError("PyPI metadata malformed: info object missing")
        version = info.get("version")
        if not isinstance(version, str) or not version:
            raise UpdateCheckError("PyPI metadata malformed: version missing")
        return UpdateCandidate(source="pypi", version=version, url=f"https://pypi.org/project/{PACKAGE_NAME}/{version}/")
    if source == "github":
        repository = metadata_repository() or DEFAULT_REPOSITORY
        payload = client.read_json(GITHUB_RELEASES_API.format(repository=repository), timeout)
        tag = payload.get("tag_name")
        html_url = payload.get("html_url")
        if not isinstance(tag, str) or not tag:
            raise UpdateCheckError("GitHub release metadata malformed: tag_name missing")
        if not isinstance(html_url, str) or not html_url:
            raise UpdateCheckError("GitHub release metadata malformed: html_url missing")
        return UpdateCandidate(source="github", version=tag.removeprefix("v"), url=html_url)
    raise UpdateCheckError(f"unsupported update source: {source}")


def newest_candidate(candidates: list[UpdateCandidate]) -> UpdateCandidate:
    """Return candidate with greatest semantic version."""

    return max(candidates, key=lambda candidate: parse_version(candidate.version))


def compare_versions(left: str, right: str) -> int:
    """Compare two semantic versions."""

    left_key = parse_version(left)
    right_key = parse_version(right)
    if left_key == right_key:
        return 0
    return 1 if left_key > right_key else -1


def parse_version(version: str) -> Version:
    """Return comparable package version fields."""

    normalized = version.removeprefix("v")
    try:
        return Version(normalized)
    except InvalidVersion as error:
        raise UpdateCheckError(f"unsupported version: {version}") from error


def update_package(
    *,
    version: str | None = None,
    source: str = "pypi",
    user: bool = False,
    client: JsonClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Install the selected package update."""

    target_version = resolve_update_version(version, source, client, timeout)
    args = ["install", "--upgrade"]
    if user:
        args.append("--user")
    if source == "pypi":
        args.append(f"{PACKAGE_NAME}=={target_version}")
    elif source == "github":
        repository = metadata_repository() or DEFAULT_REPOSITORY
        args.append(f"{PACKAGE_NAME} @ git+https://github.com/{repository}.git@v{target_version}")
    else:
        raise UpdateInstallError(f"unsupported update source: {source}")
    run_command((sys.executable, "-m", "pip", *args), error_type=UpdateInstallError)


def resolve_update_version(
    version: str | None,
    source: str,
    client: JsonClient | None,
    timeout: float,
) -> str:
    """Return explicit or latest update version."""

    if version is not None and version != "latest":
        parse_version(version)
        return version
    result = check_update(client=client, timeout=timeout, sources=(source,))
    if result.latest is None:
        return result.current_version
    return result.latest.version


def metadata_repository() -> str | None:
    """Return repository slug from installed package metadata."""

    try:
        package_metadata = metadata.metadata(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return DEFAULT_REPOSITORY
    urls = package_metadata.get_all("Project-URL") or ()
    for value in urls:
        if not value.startswith("Repository,"):
            continue
        slug = repository_slug_from_url(value.split(",", 1)[1].strip())
        if slug is not None:
            return slug
    return None


def repository_slug_from_url(url: str) -> str | None:
    """Return GitHub owner and repository slug from a URL."""

    normalized = url.removesuffix(".git").rstrip("/")
    marker = "github.com/"
    if marker not in normalized:
        return None
    suffix = normalized.split(marker, 1)[1]
    parts = [part for part in PurePosixPath(suffix).parts if part not in ("", ".")]
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def result_payload(result: UpdateCheckResult) -> dict[str, Any]:
    """Return JSON-serializable update check result."""

    return {
        "current_version": result.current_version,
        "update_available": result.update_available,
        "latest": None
        if result.latest is None
        else {
            "source": result.latest.source,
            "version": result.latest.version,
            "url": result.latest.url,
        },
        "errors": list(result.errors),
    }
