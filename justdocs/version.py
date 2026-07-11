"""Read installed justdocs version metadata."""

from importlib import metadata

from justdocs.constants import PACKAGE_NAME


class VersionMetadataError(RuntimeError):
    """Report missing installed package version metadata."""


def installed_version() -> str:
    """Return the installed package version."""

    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError as error:
        raise VersionMetadataError(
            f"installed package metadata missing: {PACKAGE_NAME}"
        ) from error
