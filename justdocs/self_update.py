"""Check and update the installed justdocs package."""

from __future__ import annotations

import json
import math
import re
import site
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from packaging.version import InvalidVersion, Version
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)

from justdocs.constants import DEFAULT_TIMEOUT_SECONDS, PACKAGE_NAME
from justdocs.install_support import run_command
from justdocs.version import (
    VersionMetadataError,
    installed_version as read_installed_version,
)


PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
GITHUB_RELEASES_API = "https://api.github.com/repos/{repository}/releases/latest"
MAX_METADATA_BYTES = 2 * 1024 * 1024


class UpdateCheckError(RuntimeError):
    """Report update metadata resolution failure."""


class UpdateSourceEmpty(UpdateCheckError):
    """Report an update source without a published package or release."""


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
    reference: str
    install_spec: str


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


@dataclass(frozen=True)
class UpdateInstallResult:
    """Store package installation outcome."""

    current_version: str
    target_version: str
    source: str
    changed: bool
    errors: tuple[str, ...] = ()


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
                payload_bytes = response.read(MAX_METADATA_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise UpdateSourceEmpty(f"no published release at {url}") from error
            raise UpdateCheckError(
                f"update check failed for {url}: HTTP {error.code}"
            ) from error
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise UpdateCheckError(f"update check failed for {url}: {error}") from error
        if len(payload_bytes) > MAX_METADATA_BYTES:
            raise UpdateCheckError(
                f"update check failed for {url}: response exceeds {MAX_METADATA_BYTES} bytes",
            )
        try:
            payload = payload_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise UpdateCheckError(
                f"update check failed for {url}: UTF-8 response required"
            ) from error
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise UpdateCheckError(
                f"update check failed for {url}: invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise UpdateCheckError(
                f"update check failed for {url}: JSON object expected"
            )
        return value


def installed_version() -> str:
    """Return installed package version."""

    try:
        return read_installed_version()
    except VersionMetadataError as error:
        raise UpdateCheckError(str(error)) from error


def check_update(
    *,
    client: JsonClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sources: tuple[str, ...] = ("pypi", "github"),
) -> UpdateCheckResult:
    """Return newest available version across enabled sources."""

    validate_timeout(timeout)
    if not sources:
        raise UpdateCheckError("update sources missing: expected pypi or github")
    current = installed_version()
    reader = UrlJsonClient() if client is None else client
    enabled_sources = tuple(dict.fromkeys(sources))
    candidates: list[UpdateCandidate] = []
    empty_sources: list[str] = []
    errors: list[str] = []
    for source in enabled_sources:
        if source not in ("pypi", "github"):
            raise UpdateCheckError(f"unsupported update source: {source}")
        try:
            candidates.append(fetch_candidate(source, reader, timeout))
        except UpdateSourceEmpty as error:
            empty_sources.append(str(error))
        except UpdateCheckError as error:
            errors.append(str(error))
    if not candidates:
        if errors:
            raise UpdateCheckError("; ".join((*empty_sources, *errors)))
        return UpdateCheckResult(
            current_version=current, latest=None, errors=tuple(empty_sources)
        )
    latest = newest_candidate(candidates)
    if compare_versions(latest.version, current) <= 0:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            errors=tuple((*empty_sources, *errors)),
        )
    return UpdateCheckResult(
        current_version=current, latest=latest, errors=tuple((*empty_sources, *errors))
    )


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
        normalized = normalize_version(version)
        return UpdateCandidate(
            source="pypi",
            version=normalized,
            url=f"https://pypi.org/project/{PACKAGE_NAME}/{normalized}/",
            reference=normalized,
            install_spec=f"{PACKAGE_NAME}=={normalized}",
        )
    if source == "github":
        repository = metadata_repository()
        payload = client.read_json(
            GITHUB_RELEASES_API.format(repository=repository), timeout
        )
        tag = payload.get("tag_name")
        html_url = payload.get("html_url")
        if not isinstance(tag, str) or not tag:
            raise UpdateCheckError(
                "GitHub release metadata malformed: tag_name missing"
            )
        if not isinstance(html_url, str) or not html_url:
            raise UpdateCheckError(
                "GitHub release metadata malformed: html_url missing"
            )
        expected_html_url = f"https://github.com/{repository}/releases/tag/{tag}"
        if html_url != expected_html_url:
            raise UpdateCheckError(
                "GitHub release metadata malformed: html_url is not canonical"
            )
        normalized = normalize_version(tag)
        return UpdateCandidate(
            source="github",
            version=normalized,
            url=html_url,
            reference=tag,
            install_spec=github_wheel_asset(payload, normalized),
        )
    raise UpdateCheckError(f"unsupported update source: {source}")


def newest_candidate(candidates: list[UpdateCandidate]) -> UpdateCandidate:
    """Return candidate with greatest semantic version."""

    if not candidates:
        raise UpdateCheckError("update candidates missing")
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


def normalize_version(version: str) -> str:
    """Return canonical PEP 440 version text."""

    return str(parse_version(version))


def validate_timeout(timeout: float) -> float:
    """Return a positive finite network timeout."""

    if not math.isfinite(timeout) or timeout <= 0:
        raise UpdateCheckError(
            f"invalid timeout {timeout}: expected a positive finite number"
        )
    return timeout


def update_package(
    *,
    version: str | None = None,
    source: str = "auto",
    client: JsonClient | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> UpdateInstallResult:
    """Install a newer package version and return the outcome."""

    candidate, errors, current = resolve_update_candidate(
        version, source, client, timeout
    )
    ordering = compare_versions(candidate.version, current)
    if ordering < 0:
        raise UpdateInstallError(
            f"requested version {candidate.version} is older than installed version {current}",
        )
    if ordering == 0:
        return UpdateInstallResult(
            current, candidate.version, candidate.source, False, errors
        )
    args = [
        "install",
        "--upgrade",
        *pip_scope_args(),
        candidate_install_spec(candidate),
    ]
    run_command((sys.executable, "-m", "pip", *args), error_type=UpdateInstallError)
    try:
        installed = normalize_version(installed_version())
    except UpdateCheckError as error:
        raise UpdateInstallError(f"update verification failed: {error}") from error
    if installed != candidate.version:
        raise UpdateInstallError(
            f"installed version {installed} does not match requested version {candidate.version}",
        )
    return UpdateInstallResult(
        current, candidate.version, candidate.source, True, errors
    )


def resolve_update_candidate(
    version: str | None,
    source: str,
    client: JsonClient | None,
    timeout: float,
) -> tuple[UpdateCandidate, tuple[str, ...], str]:
    """Return the requested candidate, metadata errors, and installed version."""

    validate_timeout(timeout)
    explicit = version is not None and version != "latest"
    if source not in ("auto", "pypi", "github"):
        raise UpdateInstallError(f"unsupported update source: {source}")
    if explicit:
        if source == "auto":
            raise UpdateInstallError(
                "explicit version requires --source pypi or --source github"
            )
        if version is None:
            raise UpdateInstallError("explicit version missing")
        normalized = normalize_version(version)
        reference = normalized if source == "pypi" else f"v{normalized}"
        candidate = explicit_candidate(source, normalized, reference)
        return candidate, (), installed_version()
    sources = ("pypi", "github") if source == "auto" else (source,)
    result = check_update(client=client, timeout=timeout, sources=sources)
    if result.latest is None:
        current = normalize_version(result.current_version)
        selected = "pypi" if source == "auto" else source
        reference = current if selected == "pypi" else f"v{current}"
        candidate = explicit_candidate(selected, current, reference)
        return candidate, result.errors, result.current_version
    return result.latest, result.errors, result.current_version


def explicit_candidate(source: str, version: str, reference: str) -> UpdateCandidate:
    """Return update metadata for an exact source and version."""

    if source == "pypi":
        return UpdateCandidate(
            source,
            version,
            f"https://pypi.org/project/{PACKAGE_NAME}/{version}/",
            reference,
            f"{PACKAGE_NAME}=={version}",
        )
    if source == "github":
        repository = metadata_repository()
        wheel = f"{PACKAGE_NAME}-{version}-py3-none-any.whl"
        return UpdateCandidate(
            source,
            version,
            f"https://github.com/{repository}/releases/tag/{reference}",
            reference,
            f"https://github.com/{repository}/releases/download/{reference}/{wheel}",
        )
    raise UpdateInstallError(f"unsupported update source: {source}")


def candidate_install_spec(candidate: UpdateCandidate) -> str:
    """Return the pip requirement for an update candidate."""

    if candidate.source not in ("pypi", "github"):
        raise UpdateInstallError(f"unsupported update source: {candidate.source}")
    return candidate.install_spec


def github_wheel_asset(payload: dict[str, Any], version: str) -> str:
    """Return the unique universal wheel URL from GitHub release metadata."""

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateCheckError("GitHub release metadata malformed: assets list missing")
    expected_version = parse_version(version)
    candidates: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        download_url = asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(download_url, str):
            continue
        try:
            distribution, wheel_version, _, tags = parse_wheel_filename(name)
        except InvalidWheelFilename:
            continue
        if (
            canonicalize_name(distribution) != canonicalize_name(PACKAGE_NAME)
            or wheel_version != expected_version
            or not any(str(tag) == "py3-none-any" for tag in tags)
        ):
            continue
        parsed = urlsplit(download_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or parsed.path.rsplit("/", 1)[-1] != name
        ):
            raise UpdateCheckError(
                "GitHub release metadata malformed: wheel URL is not canonical HTTPS"
            )
        candidates.append(download_url)
    if len(candidates) != 1:
        raise UpdateCheckError(
            f"GitHub release metadata malformed: expected one universal wheel, found {len(candidates)}",
        )
    return candidates[0]


def pip_scope_args() -> tuple[str, ...]:
    """Return pip scope arguments for the running interpreter."""

    if sys.prefix != sys.base_prefix:
        return ()
    distribution_root = installed_distribution_root()
    user_site = Path(site.getusersitepackages()).resolve()
    return ("--user",) if distribution_root.is_relative_to(user_site) else ()


def installed_distribution_root() -> Path:
    """Return the filesystem root containing the installed distribution."""

    try:
        distribution = metadata.distribution(PACKAGE_NAME)
    except metadata.PackageNotFoundError as error:
        raise UpdateInstallError(
            f"installed package metadata missing: {PACKAGE_NAME}"
        ) from error
    return Path(distribution.locate_file("")).resolve()


def metadata_repository() -> str:
    """Return repository slug from installed package metadata."""

    try:
        package_metadata = metadata.metadata(PACKAGE_NAME)
    except metadata.PackageNotFoundError as error:
        raise UpdateCheckError(
            f"installed package metadata missing: {PACKAGE_NAME}"
        ) from error
    urls = package_metadata.get_all("Project-URL") or ()
    for value in urls:
        if not value.startswith("Repository,"):
            continue
        slug = repository_slug_from_url(value.split(",", 1)[1].strip())
        if slug is not None:
            return slug
    raise UpdateCheckError(
        f"installed package repository metadata missing: {PACKAGE_NAME}"
    )


def repository_slug_from_url(url: str) -> str | None:
    """Return GitHub owner and repository slug from a URL."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        return None
    parts = parsed.path.removesuffix(".git").strip("/").split("/")
    if len(parts) != 2 or any(
        re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None for part in parts
    ):
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
