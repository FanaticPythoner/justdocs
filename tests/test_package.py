from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest.mock import patch

from justdocs import cli, global_cli, project_recipes, self_update
from justdocs.global_cli import GlobalCliError
from justdocs.plugins import (
    JustdocsLinkerError,
    LinkTarget,
    _candidate_targets,
    _dedupe_targets,
    _relative_url,
    _smart_link_markdown,
    _validate_linker_limits,
)
from justdocs.paths import (
    REQUIRED_TEMPLATE_FILES,
    REQUIRED_THEME_FILES,
    project_justfile_template,
    theme_dir,
)
from justdocs.project import (
    ProjectJustfileConfig,
    ProjectJustfileError,
    ProjectJustfileExistsError,
    ProjectJustfileInvalidPackageError,
    ProjectJustfileWriteError,
    PROJECT_CONFIG_PREFIX,
    read_project_justfile_config,
    render_project_justfile,
    split_package_spec,
    write_project_justfile,
)
from justdocs.project_recipes import ProjectRecipeConfig, ProjectRecipeError


class StaticJsonClient:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def read_json(self, url: str, timeout: float) -> dict[str, object]:
        self.urls.append(url)
        return self.payloads[url]


class EmptyJsonClient:
    def read_json(self, url: str, timeout: float) -> dict[str, object]:
        raise self_update.UpdateSourceEmpty(f"no published release at {url}")


def load_release_transaction_module() -> object:
    script = Path("scripts/release/transactional-github-release.py").resolve()
    module_name = "justdocs_transactional_github_release_test"
    specification = importlib.util.spec_from_file_location(module_name, script)
    if specification is None or specification.loader is None:
        raise AssertionError("release transaction module import failed")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def github_release_payload(version: str) -> dict[str, object]:
    """Return GitHub release metadata with one universal wheel."""

    tag = f"v{version}"
    wheel = f"justdocs-{version}-py3-none-any.whl"
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/FanaticPythoner/justdocs/releases/tag/{tag}",
        "assets": [
            {
                "name": wheel,
                "browser_download_url": (
                    f"https://github.com/FanaticPythoner/justdocs/releases/download/{tag}/{wheel}"
                ),
            },
        ],
    }


def write_transactional_gh_fixture(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import signal
            import sys
            from pathlib import Path
            from urllib.parse import parse_qs, unquote, urlsplit


            arguments = sys.argv[1:]
            calls_path = Path(os.environ["GH_CALLS"])
            state_path = Path(os.environ["GH_STATE"])
            with calls_path.open("a", encoding="utf-8") as calls:
                calls.write(json.dumps(arguments, separators=(",", ":")) + "\\n")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            transport_payload = None
            if Path(sys.argv[0]).name == "curl":
                if arguments == ["--disable", "--version"]:
                    response = os.environ.get(
                        "GH_CURL_VERSION_RESPONSE",
                        "curl 8.10.1 (x86_64-pc-linux-gnu) fixture",
                    )
                    if response:
                        print(response)
                    raise SystemExit(int(os.environ.get("GH_CURL_VERSION_EXIT", "0")))
                header_values = [
                    arguments[index + 1]
                    for index, value in enumerate(arguments[:-1])
                    if value == "-H"
                ]
                authorization_sources = [
                    value.removeprefix("@")
                    for value in header_values
                    if value.startswith("@/dev/fd/")
                ]
                transport_payload = sys.stdin.buffer.read()
                content_lengths = [
                    value.removeprefix("Content-Length: ")
                    for value in header_values
                    if value.startswith("Content-Length: ")
                ]
                if (
                    arguments[:2] != ["--disable", "--fail-with-body"]
                    or len(authorization_sources) != 1
                    or Path(authorization_sources[0]).read_text(encoding="utf-8")
                    != "Authorization: Bearer fixture-token\\n"
                    or "GH_TOKEN" in os.environ
                    or "GITHUB_TOKEN" in os.environ
                    or "fixture-token" in "\\0".join(arguments)
                    or arguments.count("--data-binary") != 1
                    or arguments[arguments.index("--data-binary") + 1] != "@-"
                    or len(content_lengths) != 1
                    or not content_lengths[0].isdecimal()
                    or int(content_lengths[0]) != len(transport_payload)
                ):
                    print("invalid curl authorization contract", file=sys.stderr)
                    raise SystemExit(67)
                endpoint = arguments[-1]
                forwarded_headers = [
                    value for value in header_values if not value.startswith("@/dev/fd/")
                ]
                request_method = arguments[arguments.index("--request") + 1]
                arguments = ["api", "-X", request_method]
                for value in forwarded_headers:
                    arguments.extend(("-H", value))
                arguments.extend(("--input", "-", endpoint))


            def save_state() -> None:
                state_path.write_text(
                    json.dumps(state, sort_keys=True, separators=(",", ":")) + "\\n",
                    encoding="utf-8",
                )


            def option(name: str, default: str | None = None) -> str | None:
                if name not in arguments:
                    return default
                return arguments[arguments.index(name) + 1]


            def add_asset(
                name: str,
                payload: bytes,
                label: str,
                content_type: str,
            ) -> dict[str, object]:
                digest = __import__("hashlib").sha256(payload).hexdigest()
                asset_id = state["nextAssetId"]
                state["nextAssetId"] += 1
                asset = {
                    "id": asset_id,
                    "hex": payload.hex(),
                    "label": label,
                    "content_type": content_type,
                    "size": len(payload),
                    "digest": f"sha256:{digest}",
                    "state": "uploaded",
                }
                state["assets"][name] = asset
                return asset


            def api_asset(name: str, asset: dict[str, object]) -> dict[str, object]:
                return {
                    "id": asset["id"],
                    "name": name,
                    "label": asset["label"] or None,
                    "content_type": asset["content_type"],
                    "size": asset["size"],
                    "digest": asset["digest"],
                    "state": asset["state"],
                    "uploader": {
                        "login": asset.get("uploaderLogin", "github-actions[bot]")
                    },
                }


            def api_release() -> dict[str, object]:
                return {
                    "id": state["databaseId"],
                    "tag_name": state["releaseTag"],
                    "immutable": state["immutable"],
                    "draft": state["isDraft"],
                    "prerelease": state["isPrerelease"],
                    "name": state["name"],
                    "body": state["description"],
                    "published_at": state["publishedAt"],
                    "author": {
                        "login": state.get("authorLogin", "github-actions[bot]")
                    },
                    "assets": [
                        api_asset(name, asset)
                        for name, asset in sorted(state["assets"].items())
                    ],
                }


            def apply_release_payload(payload: dict[str, object]) -> None:
                state["name"] = payload["name"]
                state["description"] = payload["body"]
                state["isDraft"] = payload["draft"]
                state["isPrerelease"] = payload["prerelease"]
                state["isLatest"] = payload["make_latest"] == "true"
                if not payload["draft"]:
                    state["publishedAt"] = "2026-07-12T00:00:00Z"
                if payload["draft"] and os.environ.get(
                    "GH_FORCE_DRAFT_TAG_DETACH", "1"
                ) == "1":
                    state["releaseTag"] = f"untagged-{state['databaseId']}"
                elif "tag_name" in payload:
                    state["releaseTag"] = payload["tag_name"]


            if arguments[:2] == ["api", "graphql"]:
                if any(value.startswith("ref=refs/tags/") for value in arguments):
                    requested_ref = next(
                        value.removeprefix("ref=refs/tags/")
                        for value in arguments
                        if value.startswith("ref=refs/tags/")
                    )
                    target = (
                        state["tagSha"]
                        if requested_ref == "latest"
                        else state.get("tagRefs", {}).get(requested_ref)
                    )
                    reference = None
                    if target is not None:
                        reference = {"target": {"oid": target}}
                    print(json.dumps({"data": {"repository": {"ref": reference}}}))
                    raise SystemExit(0)
                state["releaseMetadataQueryCount"] = (
                    state.get("releaseMetadataQueryCount", 0) + 1
                )
                save_state()
                if (
                    os.environ.get("GH_MUTATE_RELEASE_ON_SECOND_QUERY") == "1"
                    and state["releaseMetadataQueryCount"] == 2
                ):
                    state["name"] = "Concurrent release"
                    save_state()
                if (
                    os.environ.get("GH_TOGGLE_LATEST_ON_SECOND_QUERY") == "1"
                    and state["releaseMetadataQueryCount"] == 2
                ):
                    state["isLatest"] = not state["isLatest"]
                    save_state()
                if (
                    state.get("createCompleted")
                    and os.environ.get("GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE") == "1"
                    and not state.get("releaseQueryFailed")
                ):
                    state["releaseQueryFailed"] = True
                    if os.environ.get("GH_REPLACE_MARKER_WITH_EXTERNAL_DRAFT") == "1":
                        state["name"] = "External draft"
                        state["description"] = "external notes\\n"
                    save_state()
                    print("injected release query failure", file=sys.stderr)
                    raise SystemExit(59)
                requested_tag = next(
                    value.removeprefix("tag=")
                    for value in arguments
                    if value.startswith("tag=")
                )
                release = None
                if state["exists"] and state["releaseTag"] == requested_tag:
                    release = {
                        "databaseId": state["databaseId"],
                        "immutable": state["immutable"],
                        "isDraft": state["isDraft"],
                        "isLatest": state["isLatest"],
                        "isPrerelease": state["isPrerelease"],
                        "name": state["name"],
                        "description": state["description"],
                        "tagName": state["releaseTag"],
                    }
                print(json.dumps({"data": {"repository": {"release": release}}}))
                raise SystemExit(0)

            if arguments[:3] == ["api", "--paginate", "--slurp"]:
                if "/releases?" in arguments[-1]:
                    releases = [api_release()] if state["exists"] else []
                    releases.extend(state.get("otherReleases", []))
                    print(json.dumps([releases]))
                    raise SystemExit(0)
                release_id = int(arguments[-1].split("/releases/", 1)[1].split("/", 1)[0])
                if release_id == state["databaseId"]:
                    assets = [
                        api_asset(name, asset)
                        for name, asset in sorted(state["assets"].items())
                    ]
                else:
                    selected_release = next(
                        release
                        for release in state.get("otherReleases", [])
                        if release["id"] == release_id
                    )
                    assets = selected_release.get(
                        "fullAssets", selected_release["assets"]
                    )
                print(json.dumps([assets]))
                raise SystemExit(0)

            if (
                arguments[:1] == ["api"]
                and arguments[-1].startswith("repos/")
                and "/commits/" in arguments[-1]
            ):
                requested = unquote(arguments[-1].rsplit("/", 1)[1])
                if requested != state["targetSha"]:
                    state["tagResolveCount"] = state.get("tagResolveCount", 0) + 1
                    save_state()
                    crash_count = os.environ.get("GH_CRASH_ON_TAG_RESOLVE_COUNT")
                    if crash_count == str(state["tagResolveCount"]):
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                resolved = (
                    state["targetSha"]
                    if requested == state["targetSha"]
                    else state["tagSha"]
                )
                print(json.dumps({"sha": resolved}))
                raise SystemExit(0)

            if (
                arguments[:1] == ["api"]
                and arguments[-1].startswith("repos/")
                and "/compare/" in arguments[-1]
            ):
                print(json.dumps({"status": state["compareStatus"]}))
                raise SystemExit(0)

            if (
                arguments[:1] == ["api"]
                and arguments[-1].startswith("repos/")
                and "/releases/" in arguments[-1]
                and "/assets/" not in arguments[-1]
                and "-X" not in arguments
                and "--method" not in arguments
            ):
                release_id = int(arguments[-1].rsplit("/", 1)[1])
                selected_release = next(
                    (
                        release
                        for release in state.get("otherReleases", [])
                        if release["id"] == release_id
                    ),
                    None,
                )
                if state["exists"] and release_id == state["databaseId"]:
                    state["releaseIdQueryCount"] = (
                        state.get("releaseIdQueryCount", 0) + 1
                    )
                    if os.environ.get("GH_MUTATE_ON_RELEASE_ID_QUERY_COUNT") == str(
                        state["releaseIdQueryCount"]
                    ):
                        state["description"] = "Concurrent release mutation\\n"
                    save_state()
                    selected_release = api_release()
                if selected_release is None:
                    print("gh: Not Found (HTTP 404)", file=sys.stderr)
                    raise SystemExit(1)
                if (
                    state.get("createCompleted")
                    and os.environ.get("GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE")
                    == "1"
                    and not state.get("releaseQueryFailed")
                ):
                    state["releaseQueryFailed"] = True
                    if os.environ.get("GH_REPLACE_MARKER_WITH_EXTERNAL_DRAFT") == "1":
                        state["name"] = "External draft"
                        state["description"] = "external notes\\n"
                    save_state()
                    print("injected release query failure", file=sys.stderr)
                    raise SystemExit(59)
                print(json.dumps(selected_release))
                raise SystemExit(0)

            if (
                arguments[:1] == ["api"]
                and arguments[-1].startswith("repos/")
                and "/releases/assets/" in arguments[-1]
                and "-X" not in arguments
                and "--method" not in arguments
            ):
                asset_id = int(arguments[-1].rsplit("/", 1)[1])
                selected = next(
                    asset
                    for asset in state["assets"].values()
                    if asset["id"] == asset_id
                )
                sys.stdout.buffer.write(bytes.fromhex(selected["hex"]))
                raise SystemExit(0)

            if arguments[:1] == ["api"] and "--method" in arguments:
                method = option("--method")
                endpoint = next(
                    value for value in arguments if value.startswith("repos/")
                )
                if method == "DELETE" and "/releases/assets/" in endpoint:
                    asset_id = int(endpoint.rsplit("/", 1)[1])
                    selected = next(
                        name
                        for name, asset in state["assets"].items()
                        if asset["id"] == asset_id
                    )
                    state.setdefault("deletedAssetIds", []).append(asset_id)
                    del state["assets"][selected]
                    state["assetDeleteCount"] = state.get("assetDeleteCount", 0) + 1
                    save_state()
                    if os.environ.get("GH_CRASH_ON_ASSET_DELETE_COUNT") == str(
                        state["assetDeleteCount"]
                    ):
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                    if (
                        os.environ.get("GH_FAIL_AFTER_FIRST_ASSET_DELETE") == "1"
                        and not state.get("assetDeleteFailed")
                    ):
                        state["assetDeleteFailed"] = True
                        save_state()
                        print("injected post-delete failure", file=sys.stderr)
                        raise SystemExit(66)
                    raise SystemExit(0)

            if arguments[:1] == ["api"] and "-X" in arguments:
                method = option("-X")
                endpoint = next(
                    value
                    for value in arguments
                    if value.startswith(("repos/", "https://"))
                )

                if endpoint.startswith("https://uploads.github.com/"):
                    query = parse_qs(urlsplit(endpoint).query, keep_blank_values=True)
                    name = query["name"][0]
                    label = query["label"][0]
                    content_type = next(
                        value.removeprefix("Content-Type: ")
                        for value in arguments
                        if value.startswith("Content-Type: ")
                    )
                    input_path = option("--input")
                    payload = (
                        transport_payload
                        if input_path == "-"
                        else Path(input_path).read_bytes()
                    )
                    if (
                        os.environ.get("GH_FAIL_UPLOAD_502_STARTER") == "1"
                        and not state.get("starterUploadFailed")
                    ):
                        asset_id = state["nextAssetId"]
                        state["nextAssetId"] += 1
                        state["assets"][name] = {
                            "id": asset_id,
                            "hex": "",
                            "label": label,
                            "content_type": content_type,
                            "size": 0,
                            "digest": None,
                            "state": "starter",
                        }
                        state["starterAssetId"] = asset_id
                        state["starterUploadFailed"] = True
                        save_state()
                        print("injected upload HTTP 502", file=sys.stderr)
                        raise SystemExit(65)
                    asset = add_asset(name, payload, label, content_type)
                    state["uploadCount"] = state.get("uploadCount", 0) + 1
                    if (
                        os.environ.get("GH_INJECT_UNKNOWN_ASSET_AFTER_UPLOAD") == "1"
                        and state["uploadCount"] == 1
                    ):
                        add_asset(
                            "external.bin",
                            b"external",
                            "external",
                            "application/octet-stream",
                        )
                        save_state()
                        print("injected concurrent asset", file=sys.stderr)
                        raise SystemExit(57)
                    save_state()
                    if (
                        os.environ.get("GH_CRASH_PARTIAL_UPLOAD") == "1"
                        and state["uploadCount"] == 1
                    ):
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                    if (
                        os.environ.get("GH_FAIL_PARTIAL_UPLOAD") == "1"
                        and not state.get("partialUploadFailed")
                    ):
                        state["partialUploadFailed"] = True
                        save_state()
                        print("injected partial upload failure", file=sys.stderr)
                        raise SystemExit(57)
                    print(json.dumps(api_asset(name, asset)))
                    raise SystemExit(0)

                if endpoint.endswith("/releases") and method == "POST":
                    if os.environ.get("GH_FAIL_CREATE") == "1":
                        print("injected release create failure", file=sys.stderr)
                        raise SystemExit(60)
                    payload = json.loads(
                        Path(option("--input")).read_text(encoding="utf-8")
                    )
                    state["exists"] = True
                    state["databaseId"] = state["nextReleaseId"]
                    state["nextReleaseId"] += 1
                    state["assets"] = {}
                    state["createCompleted"] = True
                    if state["tagSha"] is None:
                        state["tagSha"] = payload["target_commitish"]
                    state["releaseTag"] = payload["tag_name"]
                    apply_release_payload(payload)
                    save_state()
                    if os.environ.get("GH_CRASH_AFTER_CREATE") == "1":
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                    print(json.dumps(api_release()))
                    raise SystemExit(0)

                if "/releases/assets/" in endpoint and method == "PATCH":
                    asset_id = int(endpoint.rsplit("/", 1)[1])
                    next_rename_count = state.get("assetRenameCount", 0) + 1
                    if (
                        os.environ.get("GH_FAIL_BEFORE_ASSET_RENAME_COUNT")
                        == str(next_rename_count)
                        and not state.get("assetRenamePreconditionFailed")
                    ):
                        state["assetRenamePreconditionFailed"] = True
                        save_state()
                        print("injected pre-rename failure", file=sys.stderr)
                        raise SystemExit(64)
                    selected = next(
                        name
                        for name, asset in state["assets"].items()
                        if asset["id"] == asset_id
                    )
                    asset = state["assets"].pop(selected)
                    name = next(
                        value.removeprefix("name=")
                        for value in arguments
                        if value.startswith("name=")
                    )
                    asset["label"] = next(
                        value.removeprefix("label=")
                        for value in arguments
                        if value.startswith("label=")
                    )
                    state["assets"][name] = asset
                    state["assetRenameCount"] = state.get("assetRenameCount", 0) + 1
                    save_state()
                    if os.environ.get("GH_CRASH_AFTER_ASSET_RENAME_COUNT") == str(
                        state["assetRenameCount"]
                    ):
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                    if (
                        os.environ.get("GH_FAIL_AFTER_ASSET_RENAME_COUNT")
                        == str(state["assetRenameCount"])
                        and not state.get("assetRenameFailed")
                    ):
                        state["assetRenameFailed"] = True
                        save_state()
                        print("injected post-rename failure", file=sys.stderr)
                        raise SystemExit(64)
                    print(json.dumps(api_asset(name, asset)))
                    raise SystemExit(0)

                if "/releases/assets/" in endpoint and method == "DELETE":
                    asset_id = int(endpoint.rsplit("/", 1)[1])
                    selected = next(
                        name
                        for name, asset in state["assets"].items()
                        if asset["id"] == asset_id
                    )
                    state.setdefault("deletedAssetIds", []).append(asset_id)
                    del state["assets"][selected]
                    save_state()
                    raise SystemExit(0)

                if "/releases/" in endpoint and "/assets/" not in endpoint:
                    release_id = int(endpoint.rsplit("/", 1)[1])
                    if release_id != state["databaseId"]:
                        print("release ID mismatch", file=sys.stderr)
                        raise SystemExit(62)
                    state.setdefault("releaseMutationIds", []).append(release_id)
                    if method == "DELETE":
                        state["exists"] = False
                        state["releaseTag"] = None
                        state["assets"] = {}
                        save_state()
                        raise SystemExit(0)
                    if method == "PATCH":
                        input_path = option("--input")
                        payload = json.loads(
                            transport_payload.decode("utf-8")
                            if input_path == "-"
                            else Path(input_path).read_text(encoding="utf-8")
                        )
                        if (
                            payload["draft"] is False
                            and os.environ.get("GH_FAIL_BEFORE_PUBLISH_PATCH") == "1"
                            and not state.get("publishPatchPreconditionFailed")
                        ):
                            state["publishPatchPreconditionFailed"] = True
                            save_state()
                            print("injected pre-publish failure", file=sys.stderr)
                            raise SystemExit(63)
                        apply_release_payload(payload)
                        save_state()
                        if (
                            payload["draft"] is False
                            and os.environ.get("GH_CRASH_AFTER_PUBLISH_PATCH") == "1"
                        ):
                            os.kill(os.getppid(), signal.SIGKILL)
                            raise SystemExit(58)
                        if (
                            payload["draft"] is False
                            and os.environ.get("GH_FAIL_AFTER_PUBLISH_PATCH") == "1"
                            and not state.get("publishPatchFailed")
                        ):
                            state["publishPatchFailed"] = True
                            save_state()
                            print("injected post-publish failure", file=sys.stderr)
                            raise SystemExit(63)
                        print(json.dumps(api_release()))
                        raise SystemExit(0)

                if "/git/refs" in endpoint:
                    if method == "DELETE":
                        state["tagSha"] = None
                    elif method in {"POST", "PATCH"}:
                        sha_field = next(
                            value for value in arguments if value.startswith("sha=")
                        )
                        state["tagSha"] = sha_field.removeprefix("sha=")
                    else:
                        raise SystemExit(98)
                    state.setdefault("tagMutationMethods", []).append(method)
                    save_state()
                    if os.environ.get("GH_CRASH_AFTER_TAG_PATCH") == "1":
                        os.kill(os.getppid(), signal.SIGKILL)
                        raise SystemExit(58)
                    raise SystemExit(0)

                if method in {"POST", "PATCH"}:
                    sha_field = next(
                        value for value in arguments if value.startswith("sha=")
                    )
                    state["tagSha"] = sha_field.removeprefix("sha=")
                else:
                    raise SystemExit(98)
                save_state()
                raise SystemExit(0)

            print(f"unsupported gh invocation: {arguments!r}", file=sys.stderr)
            raise SystemExit(97)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def stage_transaction_assets(
    root: Path,
    assets: dict[str, bytes],
    notes: str,
) -> tuple[Path, Path, Path]:
    workspace = root / "workspace"
    source_dir = workspace / "release"
    runner_temp = root / "snapshot-temp"
    source_dir.mkdir(parents=True)
    runner_temp.mkdir()
    manifest_lines = []
    for name, payload in sorted(assets.items()):
        (source_dir / name).write_bytes(payload)
        manifest_lines.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
    (source_dir / "SHA256SUMS.txt").write_text(
        "".join(manifest_lines), encoding="utf-8"
    )
    notes_file = workspace / "notes.md"
    notes_file.write_text(notes, encoding="utf-8")
    completed = subprocess.run(
        (
            sys.executable,
            "scripts/release/stage-release-inputs.py",
            "stage",
            str(source_dir),
            str(notes_file),
            str(runner_temp),
        ),
        check=False,
        env=os.environ | {"GITHUB_WORKSPACE": str(workspace)},
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    stage_root = Path(completed.stdout.strip())
    return stage_root, stage_root / "assets", stage_root / "release-notes.md"


TRANSACTION_ORIGINAL_SHA = "1" * 40
TRANSACTION_TARGET_SHA = "2" * 40
TRANSACTION_CONCURRENT_SHA = "3" * 40


def transactional_release_state(
    *,
    exists: bool,
    immutable: bool = False,
    assets: dict[str, bytes] | None = None,
    asset_labels: dict[str, str] | None = None,
    tag_sha: str | None = TRANSACTION_TARGET_SHA,
) -> dict[str, object]:
    encoded_assets = {}
    for asset_id, (name, payload) in enumerate(
        sorted((assets or {}).items()), start=901
    ):
        if name.endswith(".tar.gz"):
            content_type = "application/gzip"
        elif name.endswith(".txt"):
            content_type = "text/plain"
        else:
            content_type = "application/octet-stream"
        encoded_assets[name] = {
            "id": asset_id,
            "hex": payload.hex(),
            "label": (asset_labels or {}).get(name, f"Original {name}"),
            "content_type": content_type,
            "size": len(payload),
            "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "state": "uploaded",
        }
    return {
        "exists": exists,
        "databaseId": 701,
        "immutable": immutable,
        "isDraft": False,
        "isLatest": True,
        "isPrerelease": False,
        "name": "Original release",
        "description": "original notes\n",
        "publishedAt": "2026-07-09T13:25:43Z",
        "assets": encoded_assets,
        "nextAssetId": 901 + len(encoded_assets),
        "nextReleaseId": 702,
        "releaseTag": "latest" if exists else None,
        "tagSha": tag_sha,
        "targetSha": TRANSACTION_TARGET_SHA,
        "compareStatus": "ahead",
    }


def legacy_detached_release_state(
    *,
    progress: int = 0,
    terminal: bool = False,
) -> dict[str, object]:
    payloads = {
        "install.ps1": b"powershell installer\n",
        "install.sh": b"posix installer\n",
        "justdocs-0.1.0-py3-none-any.whl": b"wheel payload\n",
        "justdocs-0.1.0.tar.gz": b"source payload\n",
    }
    manifest = "".join(
        f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
        for name, payload in payloads.items()
    ).encode("ascii")
    payloads["SHA256SUMS.txt"] = manifest
    ordered_names = tuple(
        sorted(name for name in payloads if name != "SHA256SUMS.txt")
    ) + ("SHA256SUMS.txt",)
    asset_id_base = 1900
    assets: dict[str, dict[str, object]] = {}
    for offset, name in enumerate(ordered_names, start=1):
        payload = payloads[name]
        asset_id = asset_id_base + offset
        current_name = (
            name if terminal or offset <= progress else f"justdocs-rollback-{asset_id}"
        )
        assets[current_name] = {
            "id": asset_id,
            "hex": payload.hex(),
            "label": "",
            "content_type": (
                "text/plain"
                if name.endswith((".txt", ".ps1", ".sh"))
                else "application/gzip"
                if name.endswith(".tar.gz")
                else "application/octet-stream"
            ),
            "size": len(payload),
            "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "state": "uploaded",
        }
    target_sha = TRANSACTION_TARGET_SHA
    detached_tag = f"untagged-{hashlib.sha256(target_sha.encode()).hexdigest()[:20]}"
    return {
        "exists": True,
        "databaseId": asset_id_base - 1,
        "immutable": False,
        "isDraft": not terminal,
        "isLatest": False,
        "isPrerelease": True,
        "name": f"Latest Nightly Build ({target_sha[:12]})",
        "description": (
            "# justdocs latest\n\n"
            "- branch: `main`\n"
            f"- target commit: [`{target_sha}`]"
            f"(https://github.com/FanaticPythoner/justdocs/commit/{target_sha})\n"
            "- base stable release: none\n"
        ),
        "publishedAt": "2026-07-09T13:25:43Z",
        "assets": assets,
        "nextAssetId": asset_id_base + len(assets) + 1,
        "nextReleaseId": asset_id_base,
        "releaseTag": "latest" if terminal else detached_tag,
        "tagSha": target_sha,
        "targetSha": target_sha,
        "compareStatus": "ahead",
    }


def legacy_other_release() -> dict[str, object]:
    source = legacy_detached_release_state()
    release_id_offset = 100
    assets = []
    for name, asset in source["assets"].items():
        asset_id = asset["id"] + release_id_offset
        asset_name = (
            f"justdocs-rollback-{asset_id}"
            if name == f"justdocs-rollback-{asset['id']}"
            else name
        )
        assets.append(
            {
                "id": asset_id,
                "name": asset_name,
                "label": None,
                "content_type": asset["content_type"],
                "size": asset["size"],
                "digest": asset["digest"],
                "state": asset["state"],
                "uploader": {"login": "github-actions[bot]"},
            }
        )
    return {
        "id": source["databaseId"] + release_id_offset,
        "tag_name": (
            "untagged-" + hashlib.sha256(b"second detached release").hexdigest()[:20]
        ),
        "immutable": False,
        "draft": True,
        "prerelease": True,
        "name": source["name"],
        "body": source["description"],
        "published_at": source["publishedAt"],
        "author": {"login": "github-actions[bot]"},
        "assets": assets,
        "fullAssets": assets,
    }


def transactional_release_environment(
    root: Path,
    state: dict[str, object],
) -> tuple[dict[str, str], Path, Path, Path]:
    fake_gh = root / "gh"
    fake_curl = root / "curl"
    gh_calls_path = root / "gh-calls.jsonl"
    gh_state_path = root / "gh-state.json"
    transaction_parent = root / "transaction-temp"
    write_transactional_gh_fixture(fake_gh)
    write_transactional_gh_fixture(fake_curl)
    gh_calls_path.write_text("", encoding="utf-8")
    gh_state_path.write_text(
        json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    transaction_parent.mkdir()
    environment = os.environ | {
        "GH_CALLS": str(gh_calls_path),
        "GH_STATE": str(gh_state_path),
        "GITHUB_REPOSITORY": "FanaticPythoner/justdocs",
        "GH_TOKEN": "fixture-token",
        "PATH": os.pathsep.join((str(root), os.environ["PATH"])),
    }
    return environment, gh_calls_path, gh_state_path, transaction_parent


def release_transaction_calls(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def release_transaction_mutations(calls: list[list[str]]) -> list[list[str]]:
    mutations = [
        call
        for call in calls
        if "-X" in call or "--method" in call or "--request" in call
    ]
    for call in mutations:
        if (
            call[:1] == ["api"]
            and "--input" in call
            and call[call.index("--input") + 1] == "-"
        ):
            raise AssertionError("gh api mutation uses unknown-length standard input")
    return mutations


def release_state_projection(state: dict[str, object]) -> dict[str, object]:
    projected = {
        key: state[key]
        for key in (
            "exists",
            "databaseId",
            "immutable",
            "isDraft",
            "isLatest",
            "isPrerelease",
            "name",
            "description",
            "releaseTag",
        )
    }
    assets = state["assets"]
    if not isinstance(assets, dict):
        raise AssertionError("invalid fixture asset state")
    projected["assets"] = {
        name: {
            key: asset[key]
            for key in (
                "hex",
                "label",
                "content_type",
                "size",
                "digest",
                "state",
            )
        }
        for name, asset in assets.items()
    }
    return projected


def run_release_preflight(
    transaction_script: Path,
    environment: dict[str, str],
    transaction_parent: Path,
    *,
    tag: str = "latest",
    create_or_move_tag: str = "false",
    target_sha: str = TRANSACTION_TARGET_SHA,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            str(transaction_script),
            "preflight",
            tag,
            str(transaction_parent),
            create_or_move_tag,
            target_sha,
        ),
        check=False,
        env=environment,
        text=True,
        capture_output=True,
    )


def run_release_recover_detached(
    transaction_script: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            str(transaction_script),
            "recover-detached",
            "latest",
        ),
        check=False,
        env=environment,
        text=True,
        capture_output=True,
    )


def run_release_publish(
    transaction_script: Path,
    environment: dict[str, str],
    transaction_root: Path,
    notes_file: Path,
    dist_dir: Path,
    *,
    release_name: str = "Replacement release",
    prerelease: str = "false",
    purge_existing_assets: str = "true",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            str(transaction_script),
            "publish",
            str(transaction_root),
            release_name,
            prerelease,
            str(notes_file),
            str(dist_dir),
            purge_existing_assets,
        ),
        check=False,
        env=environment,
        text=True,
        capture_output=True,
    )


def cleanup_release_fixture(
    transaction_script: Path,
    transaction_root: Path,
    transaction_parent: Path,
    environment: dict[str, str],
    stage_root: Path | None = None,
) -> None:
    cleanup_command = (
        sys.executable,
        str(transaction_script),
        "cleanup",
        str(transaction_root),
        str(transaction_parent),
    )
    for _attempt in range(2):
        subprocess.run(
            cleanup_command,
            check=True,
            env=environment,
            text=True,
            capture_output=True,
        )
    if stage_root is not None:
        subprocess.run(
            (
                sys.executable,
                "scripts/release/stage-release-inputs.py",
                "cleanup",
                str(stage_root),
                str(stage_root.parent),
            ),
            check=True,
            text=True,
            capture_output=True,
        )


class ThemePackageTest(unittest.TestCase):
    def test_theme_dir_contains_required_assets(self) -> None:
        root = theme_dir()
        missing = [path for path in REQUIRED_THEME_FILES if not (root / path).is_file()]
        self.assertEqual([], missing)

    def test_project_templates_are_packaged(self) -> None:
        root = project_justfile_template().parent
        missing = [
            path for path in REQUIRED_TEMPLATE_FILES if not (root / path).is_file()
        ]
        self.assertEqual([], missing)

    def test_project_justfile_renders_project_local_recipes(self) -> None:
        rendered = render_project_justfile(
            ProjectJustfileConfig(
                root=Path("examples/basic"),
                mkdocs_config="mkdocs.yml",
                addr="127.0.0.1:8020",
                package="../..",
            ),
        )
        config_line = rendered.splitlines()[0]
        self.assertTrue(config_line.startswith(PROJECT_CONFIG_PREFIX))
        payload = json.loads(config_line.removeprefix(PROJECT_CONFIG_PREFIX))
        self.assertEqual("mkdocs.yml", payload["mkdocs_config"])
        self.assertEqual("127.0.0.1:8020", payload["addr"])
        self.assertEqual("../..", payload["package"])
        self.assertEqual(1, payload["schema"])
        self.assertIn("justdocs projects install --root .", rendered)
        self.assertIn("justdocs projects check --root .", rendered)
        self.assertIn("justdocs projects build --root .", rendered)
        self.assertIn("justdocs projects serve --root .", rendered)
        self.assertIn("justdocs projects serve-clean --root .", rendered)
        self.assertIn("free-port:", rendered)
        self.assertNotIn("{{ config_json }}", rendered)
        self.assertNotIn("export JUSTDOCS_", rendered)

    def test_project_justfile_write_refuses_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(ProjectJustfileExistsError):
                write_project_justfile(ProjectJustfileConfig(root=Path(directory)))
            self.assertEqual("existing\n", path.read_text(encoding="utf-8"))

    def test_project_justfile_write_overwrites_with_force(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.write_text("existing\n", encoding="utf-8")
            written = write_project_justfile(
                ProjectJustfileConfig(root=Path(directory), package="justdocs"),
                force=True,
            )
            self.assertEqual(path.resolve(), written)
            self.assertTrue(
                path.read_text(encoding="utf-8").startswith(PROJECT_CONFIG_PREFIX)
            )

    @unittest.skipIf(
        os.name == "nt", "Windows symlink privilege is environment-dependent"
    )
    def test_project_justfile_force_replaces_symlink_without_following_it(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.write_text("preserved\n", encoding="utf-8")
            path = root / "Justfile"
            path.symlink_to(outside)
            write_project_justfile(ProjectJustfileConfig(root=root), force=True)
            self.assertFalse(path.is_symlink())
            self.assertEqual("preserved\n", outside.read_text(encoding="utf-8"))

    def test_project_justfile_rejects_directory_target(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            path.mkdir()
            with self.assertRaises(ProjectJustfileWriteError):
                write_project_justfile(
                    ProjectJustfileConfig(root=Path(directory)), force=True
                )

    def test_project_justfile_rejects_malformed_stored_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Justfile"
            for payload in (
                "{",
                '{"schema":2}',
                '{"addr":1,"extra_packages":"","mkdocs_config":"mkdocs.yml",'
                '"package":"justdocs","schema":1,"venv":".venv"}',
            ):
                with self.subTest(payload=payload):
                    path.write_text(
                        PROJECT_CONFIG_PREFIX + payload + "\n", encoding="utf-8"
                    )
                    with self.assertRaises(ProjectJustfileError):
                        read_project_justfile_config(Path(directory))

    def test_project_justfile_encodes_untrusted_defaults(self) -> None:
        rendered = render_project_justfile(
            ProjectJustfileConfig(
                root=Path("."),
                mkdocs_config='docs "quoted"\nconfig.yml',
                addr="127.0.0.1:8123",
                package='justdocs==0.1.0; printf "unsafe"',
            ),
        )
        self.assertIn('"docs \\"quoted\\"\\nconfig.yml"', rendered)
        self.assertIn('"justdocs==0.1.0; printf \\"unsafe\\""', rendered)
        self.assertNotIn('docs "quoted"\nconfig.yml', rendered)

    def test_project_justfile_rejects_pip_options(self) -> None:
        for package in (
            "-e ../..",
            "--editable ../..",
            "--target /tmp/output justdocs",
        ):
            with self.subTest(package=package):
                with self.assertRaises(ProjectJustfileInvalidPackageError):
                    render_project_justfile(
                        ProjectJustfileConfig(root=Path("."), package=package)
                    )
        with self.assertRaises(ProjectJustfileInvalidPackageError):
            render_project_justfile(
                ProjectJustfileConfig(
                    root=Path("."), extra_packages="--target=/tmp/output"
                ),
            )

    def test_project_justfile_rejects_empty_required_settings(self) -> None:
        for field in ("mkdocs_config", "addr", "venv"):
            with self.subTest(field=field), self.assertRaises(ProjectJustfileError):
                render_project_justfile(
                    ProjectJustfileConfig(root=Path("."), **{field: " "})
                )

    def test_project_package_specs_preserve_single_complex_arguments(self) -> None:
        for package in (
            "../local source",
            r"C:\Program Files\justdocs",
            "justdocs[docs] @ https://example.test/justdocs-1.0.0.tar.gz",
            "justdocs; python_version >= '3.10'",
        ):
            with self.subTest(package=package):
                self.assertEqual((package,), split_package_spec(package))
        self.assertEqual(
            ("first>=1", "second<2"), split_package_spec("first>=1 second<2")
        )

    def test_source_justfile_exposes_global_cli_recipes(self) -> None:
        justfile = Path("Justfile").read_text(encoding="utf-8")
        required_terms = (
            'set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]',
            'global_python := env_var_or_default("JUSTDOCS_GLOBAL_PYTHON", python)',
            "global-install:",
            "global-uninstall:",
            "from justdocs.global_cli import main",
            "main(['install', '--project-root', '.'])",
            "main(['uninstall', '--project-root', '.'])",
            "justdocs.cli projects init",
        )
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, justfile)

    def test_cli_projects_init_writes_project_justfile(self) -> None:
        with TemporaryDirectory() as directory:
            exit_code = cli.main(
                [
                    "projects",
                    "init",
                    "--root",
                    directory,
                    "--mkdocs-config",
                    "docs.yml",
                    "--addr",
                    "127.0.0.1:9001",
                    "--package",
                    "justdocs==0.1.0",
                ],
            )
            self.assertEqual(0, exit_code)
            stored = read_project_justfile_config(Path(directory))
            self.assertEqual("docs.yml", stored.mkdocs_config)
            self.assertEqual("127.0.0.1:9001", stored.addr)
            self.assertEqual("justdocs==0.1.0", stored.package)

    def test_cli_without_args_prints_command_hub(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli.main([])
        rendered = output.getvalue()
        self.assertEqual(0, exit_code)
        self.assertIn("Common commands:", rendered)
        self.assertIn("justdocs projects init --root docs-project", rendered)
        self.assertIn("justdocs check-update", rendered)
        self.assertIn("justdocs update", rendered)

    def test_cli_rejects_removed_command_aliases(self) -> None:
        for command in (("self", "check-update"), ("project", "check"), ("init",)):
            with (
                self.subTest(command=command),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main(command)
            self.assertEqual(2, raised.exception.code)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(("version", "--check"))
        self.assertEqual(2, raised.exception.code)

    def test_cli_project_recipe_dispatches_config(self) -> None:
        with patch.object(project_recipes, "check") as check:
            exit_code = cli.main(
                [
                    "projects",
                    "check",
                    "--root",
                    "docs-project",
                    "--mkdocs-config",
                    "docs.yml",
                    "--addr",
                    "127.0.0.1:9001",
                    "--port",
                    "9002",
                    "--package",
                    "justdocs==0.1.0",
                    "--extra-packages",
                    "pymdown-extensions==10.12",
                    "--venv",
                    ".docs-venv",
                    "--python",
                    "python",
                ],
            )
        self.assertEqual(0, exit_code)
        (config,) = check.call_args.args
        self.assertEqual(Path("docs-project"), config.root)
        self.assertEqual("docs.yml", config.mkdocs_config)
        self.assertEqual("127.0.0.1:9001", config.addr)
        self.assertEqual("9002", config.port)
        self.assertEqual("justdocs==0.1.0", config.package)
        self.assertEqual("pymdown-extensions==10.12", config.extra_packages)
        self.assertEqual(Path(".docs-venv"), config.venv)
        self.assertEqual("python", config.python)

    def test_cli_project_recipe_loads_generated_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_project_justfile(
                ProjectJustfileConfig(
                    root=root,
                    mkdocs_config="docs.yml",
                    addr="127.0.0.1:9123",
                    package="justdocs==2.0.0",
                    extra_packages="pymdown-extensions==10.12 other-package>=1",
                    venv=".docs-venv",
                ),
            )
            with patch.object(project_recipes, "check") as check:
                exit_code = cli.main(["projects", "check", "--root", str(root)])
        self.assertEqual(0, exit_code)
        (config,) = check.call_args.args
        self.assertEqual("docs.yml", config.mkdocs_config)
        self.assertEqual("127.0.0.1:9123", config.addr)
        self.assertEqual("justdocs==2.0.0", config.package)
        self.assertEqual(
            "pymdown-extensions==10.12 other-package>=1", config.extra_packages
        )
        self.assertEqual(Path(".docs-venv"), config.venv)
        self.assertEqual("9123", config.port_value)

    def test_self_update_selects_newest_metadata_candidate(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        client = StaticJsonClient(
            {
                self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}},
                github_url: github_release_payload("0.3.0"),
            },
        )
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
        ):
            result = self_update.check_update(client=client, timeout=1.0)
        self.assertTrue(result.update_available)
        self.assertIsNotNone(result.latest)
        self.assertEqual("github", result.latest.source)
        self.assertEqual("0.3.0", result.latest.version)
        self.assertEqual((), result.errors)
        self.assertEqual([self_update.PYPI_JSON_URL, github_url], client.urls)

    def test_self_update_reports_current_when_candidate_not_newer(self) -> None:
        client = StaticJsonClient(
            {self_update.PYPI_JSON_URL: {"info": {"version": "0.1.0"}}}
        )
        with patch.object(self_update, "installed_version", return_value="0.1.0"):
            result = self_update.check_update(
                client=client, timeout=1.0, sources=("pypi",)
            )
        self.assertFalse(result.update_available)
        self.assertIsNone(result.latest)

    def test_self_update_reports_unpublished_sources_without_failure(self) -> None:
        with patch.object(self_update, "installed_version", return_value="0.1.0"):
            result = self_update.check_update(client=EmptyJsonClient(), timeout=1.0)
        self.assertFalse(result.update_available)
        self.assertEqual(2, len(result.errors))
        self.assertTrue(
            all(error.startswith("no published release at ") for error in result.errors)
        )

    def test_self_update_fails_when_empty_source_coexists_with_transport_failure(
        self,
    ) -> None:
        class MixedJsonClient:
            def read_json(self, url: str, timeout: float) -> dict[str, object]:
                if url == self_update.PYPI_JSON_URL:
                    raise self_update.UpdateSourceEmpty(
                        f"no published release at {url}"
                    )
                raise self_update.UpdateCheckError(
                    f"update check failed for {url}: unavailable"
                )

        with self.assertRaises(self_update.UpdateCheckError):
            self_update.check_update(client=MixedJsonClient(), timeout=1.0)

    def test_self_update_uses_pep440_ordering(self) -> None:
        self.assertLess(self_update.compare_versions("1.0.0rc1", "1.0.0"), 0)
        self.assertGreater(self_update.compare_versions("1.0.0.post1", "1.0.0"), 0)
        self.assertEqual(0, self_update.compare_versions("v1.0.0", "1.0.0"))

    def test_self_update_accepts_only_canonical_github_repository_urls(self) -> None:
        self.assertEqual(
            "FanaticPythoner/justdocs",
            self_update.repository_slug_from_url(
                "https://github.com/FanaticPythoner/justdocs.git"
            ),
        )
        for url in (
            "http://github.com/FanaticPythoner/justdocs",
            "https://example.test/github.com/FanaticPythoner/justdocs",
            "https://github.com/FanaticPythoner/justdocs/releases",
            "https://github.com/FanaticPythoner/justdocs?ref=main",
            "https://github.com@attacker.test/FanaticPythoner/justdocs",
            "git@github.com:FanaticPythoner/justdocs.git",
        ):
            with self.subTest(url=url):
                self.assertIsNone(self_update.repository_slug_from_url(url))

    def test_self_update_requires_installed_repository_metadata(self) -> None:
        with (
            patch.object(
                self_update.metadata,
                "metadata",
                side_effect=self_update.metadata.PackageNotFoundError,
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.metadata_repository()

    def test_self_update_requires_unique_release_wheel_asset(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        payload = github_release_payload("0.2.0")
        payload["assets"] = []
        client = StaticJsonClient({github_url: payload})
        with (
            patch.object(self_update, "installed_version", return_value="0.1.0"),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.check_update(client=client, timeout=1.0, sources=("github",))

    def test_self_update_rejects_oversized_metadata(self) -> None:
        class OversizedResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit: int) -> bytes:
                return b"x" * limit

        with (
            patch.object(
                self_update.urllib.request, "urlopen", return_value=OversizedResponse()
            ),
            self.assertRaises(self_update.UpdateCheckError),
        ):
            self_update.UrlJsonClient().read_json(self_update.PYPI_JSON_URL, 1.0)

    def test_self_update_builds_pypi_install_command(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(self_update, "pip_scope_args", return_value=("--user",)),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(version="0.2.0", source="pypi")
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--user",
                "justdocs==0.2.0",
            ),
            command,
        )
        self.assertTrue(result.changed)
        self.assertEqual("0.2.0", result.target_version)

    def test_self_update_builds_github_install_command(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.2.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            patch.object(self_update, "pip_scope_args", return_value=()),
            patch.object(self_update, "run_command") as run_command,
        ):
            self_update.update_package(version="0.2.0", source="github")
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "https://github.com/FanaticPythoner/justdocs/releases/download/"
                "v0.2.0/justdocs-0.2.0-py3-none-any.whl",
            ),
            command,
        )

    def test_cli_update_dispatches_update_command(self) -> None:
        output = StringIO()
        result = self_update.UpdateInstallResult("0.1.0", "0.2.0", "github", True)
        with (
            patch.object(
                self_update, "update_package", return_value=result
            ) as update_package,
            redirect_stdout(output),
        ):
            exit_code = cli.main(["update", "--source", "github", "--version", "0.2.0"])
        self.assertEqual(0, exit_code)
        update_package.assert_called_once_with(
            version="0.2.0",
            source="github",
            timeout=self_update.DEFAULT_TIMEOUT_SECONDS,
        )
        self.assertIn("updated justdocs 0.1.0 -> 0.2.0 from github", output.getvalue())

    def test_cli_update_reports_current_without_claiming_install(self) -> None:
        output = StringIO()
        result = self_update.UpdateInstallResult("0.2.0", "0.2.0", "pypi", False)
        with (
            patch.object(self_update, "update_package", return_value=result),
            redirect_stdout(output),
        ):
            exit_code = cli.main(["update"])
        self.assertEqual(0, exit_code)
        self.assertEqual("justdocs 0.2.0 is current\n", output.getvalue())

    def test_self_update_auto_installs_newest_release_wheel(self) -> None:
        github_url = self_update.GITHUB_RELEASES_API.format(
            repository="FanaticPythoner/justdocs"
        )
        client = StaticJsonClient(
            {
                self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}},
                github_url: github_release_payload("0.3.0"),
            },
        )
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.3.0")
            ),
            patch.object(
                self_update,
                "metadata_repository",
                return_value="FanaticPythoner/justdocs",
            ),
            patch.object(self_update, "pip_scope_args", return_value=()),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(client=client, timeout=1.0)
        self.assertEqual("github", result.source)
        self.assertIn(
            "releases/download/v0.3.0/justdocs-0.3.0-py3-none-any.whl",
            run_command.call_args.args[0][-1],
        )

    def test_self_update_skips_current_version(self) -> None:
        client = StaticJsonClient(
            {self_update.PYPI_JSON_URL: {"info": {"version": "0.2.0"}}}
        )
        with (
            patch.object(self_update, "installed_version", return_value="0.2.0"),
            patch.object(self_update, "run_command") as run_command,
        ):
            result = self_update.update_package(
                source="pypi", client=client, timeout=1.0
            )
        self.assertFalse(result.changed)
        run_command.assert_not_called()

    def test_self_update_rejects_unverified_install_result(self) -> None:
        with (
            patch.object(
                self_update, "installed_version", side_effect=("0.1.0", "0.1.0")
            ),
            patch.object(self_update, "run_command"),
            self.assertRaises(self_update.UpdateInstallError),
        ):
            self_update.update_package(version="0.2.0", source="pypi")

    def test_self_update_rejects_downgrade_and_ambiguous_explicit_source(self) -> None:
        with patch.object(self_update, "installed_version", return_value="0.2.0"):
            with self.assertRaises(self_update.UpdateInstallError):
                self_update.update_package(version="0.1.0", source="pypi")
            with self.assertRaises(self_update.UpdateInstallError):
                self_update.update_package(version="0.3.0", source="auto")

    def test_self_update_rejects_invalid_timeouts_and_empty_sources(self) -> None:
        for timeout in (0.0, -1.0, float("inf"), float("nan")):
            with (
                self.subTest(timeout=timeout),
                self.assertRaises(self_update.UpdateCheckError),
            ):
                self_update.check_update(timeout=timeout)
        with self.assertRaises(self_update.UpdateCheckError):
            self_update.check_update(sources=())

    def test_self_update_selects_pip_scope_from_interpreter(self) -> None:
        with (
            patch.object(sys, "prefix", "/venv"),
            patch.object(sys, "base_prefix", "/base"),
        ):
            self.assertEqual((), self_update.pip_scope_args())
        with TemporaryDirectory() as directory:
            user_site = Path(directory) / "user-site"
            system_site = Path(directory) / "system-site"
            prefix_collision = Path(directory) / "user-site-shadow"
            user_site.mkdir()
            system_site.mkdir()
            prefix_collision.mkdir()
            for distribution_root, expected in (
                (user_site, ("--user",)),
                (system_site, ()),
                (prefix_collision, ()),
            ):
                with (
                    self.subTest(distribution_root=distribution_root),
                    patch.object(sys, "prefix", "/base"),
                    patch.object(sys, "base_prefix", "/base"),
                    patch.object(
                        self_update.site,
                        "getusersitepackages",
                        return_value=str(user_site),
                    ),
                    patch.object(
                        self_update,
                        "installed_distribution_root",
                        return_value=distribution_root.resolve(),
                    ),
                ):
                    self.assertEqual(expected, self_update.pip_scope_args())

    def test_self_update_requires_installed_distribution_for_scope(self) -> None:
        with (
            patch.object(
                self_update.metadata,
                "distribution",
                side_effect=self_update.metadata.PackageNotFoundError,
            ),
            self.assertRaises(self_update.UpdateInstallError),
        ):
            self_update.installed_distribution_root()

    def test_cli_check_update_dispatches_top_level_command(self) -> None:
        result = self_update.UpdateCheckResult(current_version="0.1.0", latest=None)
        output = StringIO()
        with (
            patch.object(
                self_update, "check_update", return_value=result
            ) as check_update,
            redirect_stdout(output),
        ):
            exit_code = cli.main(
                ["check-update", "--source", "pypi", "--timeout", "1.5"]
            )
        self.assertEqual(0, exit_code)
        check_update.assert_called_once_with(timeout=1.5, sources=("pypi",))
        self.assertIn("current: 0.1.0", output.getvalue())
        self.assertIn("latest: current", output.getvalue())

    def test_release_pipeline_uses_dist_action_pypi_publish_and_release_assets(
        self,
    ) -> None:
        release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
        latest = Path(".github/workflows/latest.yml").read_text(encoding="utf-8")
        pr_distribution = Path(
            ".github/workflows/pr-python-dist-comment.yml"
        ).read_text(encoding="utf-8")
        pr_distribution_lifecycle = Path(
            ".github/workflows/pr-python-dist-lifecycle.yml"
        ).read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        build_action = Path(".github/actions/build-dist/action.yml").read_text(
            encoding="utf-8"
        )
        release_action = Path(".github/actions/release-assets/action.yml").read_text(
            encoding="utf-8"
        )
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).read_text(encoding="utf-8")
        build_script = Path("scripts/release/build-python-package.sh").read_text(
            encoding="utf-8"
        )
        metadata_script = Path("scripts/release/resolve-release-metadata.sh").read_text(
            encoding="utf-8"
        )
        release_notes_script = Path("scripts/release/write-release-notes.sh").read_text(
            encoding="utf-8"
        )
        create_next_release = Path("scripts/release/create-next-release.py").read_text(
            encoding="utf-8"
        )
        verify_github_release = Path(
            "scripts/release/verify-github-release.py"
        ).read_text(encoding="utf-8")
        sync_pr_distribution = Path(
            "scripts/ci/sync-pr-python-dist-comment.py"
        ).read_text(encoding="utf-8")
        reusable = Path(
            ".github/workflows/reusable-build-python-package.yml"
        ).read_text(encoding="utf-8")
        security = Path(".github/workflows/security.yml").read_text(encoding="utf-8")
        dependabot = Path(".github/dependabot.yml").read_text(encoding="utf-8")
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        checkout_action = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
        setup_python_action = (
            "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
        )
        upload_action = (
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        )
        download_action = (
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
        )
        pypi_action = (
            "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b"
        )
        attest_action = (
            "actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373"
        )
        codeql_init_action = (
            "github/codeql-action/init@99df26d4f13ea111d4ec1a7dddef6063f76b97e9"
        )
        codeql_analyze_action = (
            "github/codeql-action/analyze@99df26d4f13ea111d4ec1a7dddef6063f76b97e9"
        )
        dependency_review_action = (
            "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294"
        )
        workflows = "\n".join(
            (
                ci,
                latest,
                release,
                reusable,
                security,
                pr_distribution,
                pr_distribution_lifecycle,
            )
        )
        action_sources = {
            "ci": ci,
            "latest": latest,
            "release": release,
            "pr-distribution": pr_distribution,
            "pr-distribution-lifecycle": pr_distribution_lifecycle,
            "reusable": reusable,
            "security": security,
            "build-action": build_action,
            "release-action": release_action,
        }
        action_refs = {
            source_name: {
                line.split("uses:", 1)[1].split(" #", 1)[0].strip()
                for line in source.splitlines()
                if line.lstrip().startswith("uses: ")
            }
            for source_name, source in action_sources.items()
        }
        for source_name, references in action_refs.items():
            for reference in references:
                if reference.startswith("./"):
                    continue
                with self.subTest(source=source_name, action=reference):
                    self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")

        def workflow_steps(source: str) -> tuple[str, ...]:
            lines = source.splitlines()
            steps: list[str] = []
            for start, line in enumerate(lines):
                if not line.startswith("      - "):
                    continue
                end = start + 1
                while end < len(lines):
                    candidate = lines[end]
                    indentation = len(candidate) - len(candidate.lstrip())
                    if candidate.strip() and indentation <= 6:
                        break
                    end += 1
                steps.append("\n".join(lines[start:end]))
            return tuple(steps)

        self.assertIn(pypi_action, release)
        self.assertIn("PYPI_API_TOKEN", release)
        self.assertNotIn("PYPI_TRUSTED_PUBLISHING", release)
        self.assertIn("Publish to PyPI with trusted publishing", release)
        self.assertIn("Publish to PyPI with API token", release)
        self.assertIn("mode=trusted", release)
        self.assertNotIn("mode=none", release)
        self.assertIn("artifacts/pypi", release)
        self.assertIn("id-token: write", release)
        self.assertIn("verify-pypi", release)
        self.assertIn("python-version: '3.14'", ci)
        self.assertIn("python-version: '3.14t'", ci)
        self.assertIn("python-version: '3.13t'", ci)
        self.assertIn("os: macos-15", ci)
        self.assertIn("os: windows-2025", ci)
        self.assertIn(setup_python_action, ci)
        self.assertEqual(
            {
                "ci": {
                    checkout_action,
                    setup_python_action,
                    upload_action,
                    download_action,
                    "./.github/actions/build-dist",
                },
                "latest": {
                    checkout_action,
                    setup_python_action,
                    download_action,
                    "./.github/actions/release-assets",
                    "./.github/workflows/reusable-build-python-package.yml",
                },
                "release": {
                    checkout_action,
                    setup_python_action,
                    download_action,
                    pypi_action,
                    attest_action,
                    "./.github/actions/release-assets",
                    "./.github/workflows/reusable-build-python-package.yml",
                },
                "pr-distribution": {
                    checkout_action,
                    setup_python_action,
                },
                "pr-distribution-lifecycle": {
                    checkout_action,
                    setup_python_action,
                },
                "reusable": {
                    checkout_action,
                    upload_action,
                    "./.github/actions/build-dist",
                },
                "security": {
                    checkout_action,
                    setup_python_action,
                    dependency_review_action,
                    codeql_init_action,
                    codeql_analyze_action,
                },
                "build-action": {setup_python_action},
                "release-action": set(),
            },
            action_refs,
        )
        for workflow_name, workflow_source, artifact_name in (
            ("ci", ci, "justdocs-python-dist"),
            ("latest", latest, "python-dist"),
            ("release", release, "python-dist"),
        ):
            download_steps = tuple(
                step
                for step in workflow_steps(workflow_source)
                if f"uses: {download_action}" in step
            )
            self.assertTrue(download_steps)
            for step_index, step in enumerate(download_steps):
                with self.subTest(
                    workflow=workflow_name,
                    step=step_index,
                    contract="download-artifact",
                ):
                    self.assertIn("digest-mismatch: error", step)
                    self.assertIn(f"name: {artifact_name}", step)
        for workflow_name, workflow_source, artifact_name in (
            ("ci", ci, "justdocs-python-dist"),
            ("reusable", reusable, "python-dist"),
        ):
            upload_steps = tuple(
                step
                for step in workflow_steps(workflow_source)
                if f"uses: {upload_action}" in step
            )
            self.assertTrue(upload_steps)
            for step_index, step in enumerate(upload_steps):
                with self.subTest(
                    workflow=workflow_name,
                    step=step_index,
                    contract="upload-artifact",
                ):
                    self.assertIn("archive: true", step)
                    self.assertIn(f"name: {artifact_name}", step)
        self.assertNotIn("pattern: python-dist", workflows)
        self.assertNotIn("merge-multiple: true", workflows)
        self.assertIn("artifact-roundtrip:", ci)
        self.assertIn("name: justdocs-python-dist", ci)
        self.assertIn("retention-days: 30", ci)
        self.assertIn("overwrite: true", ci)
        self.assertIn("sha256sum --check SHA256SUMS.txt", ci)
        self.assertIn("package-ecosystem: github-actions", dependabot)
        self.assertIn("groups:\n      github-actions:\n        patterns:", dependabot)
        self.assertIn('- "*"', dependabot)
        self.assertIn("pip-audit==2.10.1", security)
        self.assertIn("python -m pip_audit --strict --progress-spinner=off .", security)
        self.assertIn(dependency_review_action, security)
        self.assertIn("uses: ./.github/actions/build-dist", ci)
        self.assertIn(
            "uses: ./.github/workflows/reusable-build-python-package.yml", release
        )
        self.assertNotIn("secrets: inherit", release)
        self.assertNotIn("secrets: inherit", latest)
        self.assertIn("uses: ./.github/actions/release-assets", release)
        self.assertIn("uses: ./.github/actions/release-assets", latest)
        self.assertIn(
            "concurrency:\n  group: release-${{ github.event_name == "
            "'workflow_dispatch' && inputs.tag || github.ref_name }}\n"
            "  cancel-in-progress: false",
            release,
        )
        self.assertIn(
            "concurrency:\n  group: latest-main\n  cancel-in-progress: true",
            latest,
        )
        for workflow in (release, latest):
            self.assertIn(
                "concurrency:\n"
                "      group: github-release-mutation-${{ github.repository }}\n"
                "      cancel-in-progress: false\n"
                "      queue: max",
                workflow,
            )
        self.assertIn("scripts/release/build-python-package.sh", build_action)
        self.assertIn("SHA256SUMS.txt", build_script)
        self.assertIn(
            "cp dist/* install.sh install.ps1 artifacts/release/", build_script
        )
        self.assertIn("scripts/release/check-pypi-artifacts.py", release)
        self.assertIn("--stage-dir artifacts/pypi", release)
        self.assertIn("scripts/release/verify-github-release.py", release)
        self.assertIn("Write expected GitHub release notes", release)
        self.assertNotIn(
            "if: ${{ needs.publish.outputs.pypi_published == 'true' }}", release
        )
        self.assertNotIn("- name: Stage PyPI artifacts", release)
        self.assertIn('"$PYPI_STATE" != "partial"', release)
        self.assertIn("version.is_prerelease", metadata_script)
        self.assertNotRegex(release_notes_script, r"\b(?:mapfile|readarray)\b")
        self.assertNotIn("release_tag:", reusable)
        self.assertIn("https://uploads.github.com/repos/", transaction_script)
        self.assertIn("def _create_release(", transaction_script)
        self.assertNotIn('"release",\n        "create"', transaction_script)
        self.assertNotIn("purge-github-release-assets.sh", release_action)
        self.assertNotIn("ensure-github-release.sh", release_action)
        self.assertEqual(4, release_action.count("stage-release-inputs.py"))
        self.assertEqual(5, release_action.count("transactional-github-release.py"))
        self.assertIn(
            "- name: Cleanup release transaction\n      if: always()",
            release_action,
        )
        self.assertLess(
            release_action.index("- name: Verify staged inputs"),
            release_action.index("- name: Preflight release transaction"),
        )
        self.assertLess(
            release_action.index('recover-detached "$RELEASE_TAG"'),
            release_action.index('target_sha="$(git rev-parse'),
        )
        self.assertLess(
            release_action.index("- name: Preflight release transaction"),
            release_action.index("- name: Publish release transaction"),
        )
        self.assertNotIn("- name: Create or move tag", release_action)
        self.assertIn(
            '"$RELEASE_TAG" "$RUNNER_TEMP" "$CREATE_OR_MOVE_TAG" "$target_sha"',
            release_action,
        )
        self.assertIn("git rev-parse --verify 'HEAD^{commit}'", release_action)
        self.assertNotIn("TARGET_SHA: ${{ github.sha }}", release_action)
        self.assertIn(
            'release_validate_boolean prerelease "$PRERELEASE"', release_action
        )
        self.assertIn(
            'release_validate_boolean purge_existing_assets "$PURGE_EXISTING_ASSETS"',
            release_action,
        )
        self.assertIn(
            'release_validate_boolean create_or_move_tag "$CREATE_OR_MOVE_TAG"',
            release_action,
        )
        self.assertNotIn("continue-on-error", release_action)
        for run_block in release_action.split("run: |")[1:]:
            with self.subTest(run_block=run_block[:80]):
                self.assertNotIn("${{ inputs.", run_block.split("\n    - name:", 1)[0])
        for workflow_name, workflow_source in (
            ("release", release),
            ("latest", latest),
        ):
            for run_block in workflow_source.split("run: |")[1:]:
                script_lines: list[str] = []
                for line in run_block.splitlines():
                    indentation = len(line) - len(line.lstrip())
                    if line.strip() and indentation <= 6:
                        break
                    script_lines.append(line)
                with self.subTest(workflow=workflow_name, run_block=run_block[:80]):
                    self.assertNotIn("${{", "\n".join(script_lines))
        self.assertIn("packaging>=24", pyproject)
        self.assertNotIn("packaging>=24,<", pyproject)
        self.assertIn('requires = ["setuptools==83.0.0"]', pyproject)
        self.assertIn('"build==1.5.1"', pyproject)
        self.assertIn('"twine==6.2.0"', pyproject)
        self.assertIn("SOURCE_DATE_EPOCH", build_script)
        self.assertIn("PYTHONHASHSEED", build_script)
        self.assertIn("gzip.GzipFile", build_script)
        self.assertIn('license = "GPL-3.0-only"', pyproject)
        self.assertIn('license-files = ["LICENSE"]', pyproject)
        self.assertIn('Changelog = "https://github.com/', pyproject)
        self.assertEqual(
            ["include CHANGELOG.md", "include LICENSE", "include README.md"],
            Path("MANIFEST.in").read_text(encoding="utf-8").splitlines(),
        )
        self.assertIn("Programming Language :: Python :: 3.14", pyproject)
        self.assertIn(
            "Programming Language :: Python :: Free Threading :: 2 - Beta", pyproject
        )
        self.assertIn('"push",', create_next_release)
        self.assertIn("--atomic", create_next_release)
        self.assertIn("CHANGELOG.md", create_next_release)
        self.assertIn("GitHub release asset inventory mismatch", verify_github_release)
        self.assertIn("workflow_run:", pr_distribution)
        self.assertIn("pull-requests: write", pr_distribution)
        self.assertIn("persist-credentials: false", pr_distribution)
        self.assertIn("sync-pr-python-dist-comment.py", pr_distribution)
        self.assertIn("pull_request_target:", pr_distribution_lifecycle)
        self.assertIn("actions: write", pr_distribution_lifecycle)
        self.assertIn("persist-credentials: false", pr_distribution_lifecycle)
        self.assertIn("--closed-pull-request", pr_distribution_lifecycle)
        self.assertIn("COMMENT_MARKER", sync_pr_distribution)
        self.assertIn("Security: packages contain unreviewed", sync_pr_distribution)

    def test_pypi_artifact_checker_classifies_and_stages_exact_subsets(self) -> None:
        checker_path = Path("scripts/release/check-pypi-artifacts.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "justdocs_check_pypi_artifacts",
            checker_path,
        )
        if specification is None or specification.loader is None:
            self.fail("PyPI artifact checker import failed")
        checker = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(checker)

        class Response:
            def __init__(self, payload: dict[str, object]) -> None:
                self.encoded = json.dumps(payload).encode("utf-8")

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return self.encoded

        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            wheel = artifacts / "justdocs-1.2.3-py3-none-any.whl"
            source = artifacts / "justdocs-1.2.3.tar.gz"
            wheel.write_bytes(b"wheel")
            source.write_bytes(b"source")
            hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (wheel, source)
            }

            not_found = checker.urllib.error.HTTPError(
                "https://pypi.org/pypi/justdocs/1.2.3/json",
                404,
                "not found",
                None,
                None,
            )
            with patch.object(
                checker.urllib.request,
                "urlopen",
                side_effect=not_found,
            ):
                self.assertEqual(
                    ("absent", tuple(sorted(hashes))),
                    checker.publication_state("justdocs", "1.2.3", artifacts),
                )

            exact_payload = {
                "info": {"version": "1.2.3"},
                "urls": [
                    {
                        "filename": name,
                        "digests": {"sha256": digest},
                    }
                    for name, digest in sorted(hashes.items())
                ],
            }
            with patch.object(
                checker.urllib.request,
                "urlopen",
                return_value=Response(exact_payload),
            ):
                self.assertEqual(
                    ("exact", ()),
                    checker.publication_state("justdocs", "1.2.3", artifacts),
                )

            normalized_payload = exact_payload | {"info": {"version": "1.2.3.0"}}
            with patch.object(
                checker.urllib.request,
                "urlopen",
                return_value=Response(normalized_payload),
            ):
                self.assertEqual(
                    ("exact", ()),
                    checker.publication_state("justdocs", "1.2.3", artifacts),
                )

            partial_payload = {
                "info": {"version": "1.2.3"},
                "urls": [
                    {
                        "filename": wheel.name,
                        "digests": {"sha256": hashes[wheel.name]},
                    }
                ],
            }
            with patch.object(
                checker.urllib.request,
                "urlopen",
                return_value=Response(partial_payload),
            ):
                state, missing = checker.publication_state(
                    "justdocs",
                    "1.2.3",
                    artifacts,
                )
            self.assertEqual("partial", state)
            self.assertEqual((source.name,), missing)
            stage = root / "pypi-stage"
            checker._stage_missing(artifacts, stage, missing)
            self.assertEqual([source.name], [path.name for path in stage.iterdir()])
            self.assertEqual(source.read_bytes(), (stage / source.name).read_bytes())

            mismatched_payload = {
                "info": {"version": "1.2.3"},
                "urls": [
                    {
                        "filename": wheel.name,
                        "digests": {"sha256": "0" * 64},
                    }
                ],
            }
            with (
                patch.object(
                    checker.urllib.request,
                    "urlopen",
                    return_value=Response(mismatched_payload),
                ),
                self.assertRaisesRegex(
                    checker.PyPIArtifactError,
                    "PyPI artifact mismatch",
                ),
            ):
                checker.publication_state("justdocs", "1.2.3", artifacts)

            invalid_artifacts = root / "invalid-artifacts"
            invalid_artifacts.mkdir()
            (invalid_artifacts / "invalid.whl").mkdir()
            with (
                patch.object(checker.urllib.request, "urlopen") as remote_query,
                self.assertRaisesRegex(
                    checker.PyPIArtifactError,
                    "invalid Python distribution artifact inventory",
                ),
            ):
                checker.publication_state(
                    "justdocs",
                    "1.2.3",
                    invalid_artifacts,
                )
            remote_query.assert_not_called()

            if os.name == "nt":
                renamed_wheel = wheel.with_suffix(".renamed.whl")
                with checker._open_local_artifacts(artifacts):
                    with self.assertRaises(OSError):
                        wheel.write_bytes(b"mutated")
                    with self.assertRaises(OSError):
                        wheel.rename(renamed_wheel)
                wheel.write_bytes(b"wheel")
                artifacts_junction = root / "artifacts-junction"
                junction = subprocess.run(
                    (
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(artifacts_junction),
                        str(artifacts),
                    ),
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, junction.returncode, junction.stderr)
                with (
                    patch.object(checker.urllib.request, "urlopen") as remote_query,
                    self.assertRaisesRegex(
                        checker.PyPIArtifactError,
                        "invalid artifacts directory",
                    ),
                ):
                    checker.publication_state(
                        "justdocs",
                        "1.2.3",
                        artifacts_junction,
                    )
                remote_query.assert_not_called()

            with (
                patch.object(
                    checker,
                    "_publication_state",
                    side_effect=(
                        ("partial", (source.name,)),
                        checker.PyPIRemoteError("temporary query failure"),
                        ("exact", ()),
                    ),
                ) as publication,
                patch.object(
                    checker.time,
                    "monotonic",
                    side_effect=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
                ),
                patch.object(checker.time, "sleep"),
            ):
                self.assertEqual(
                    "exact",
                    checker._wait_for_exact(
                        "justdocs",
                        "1.2.3",
                        hashes,
                        1.0,
                        10.0,
                    ),
                )
            self.assertEqual(
                [9.0, 7.0, 5.0],
                [call.args[3] for call in publication.call_args_list],
            )

            server_error = checker.urllib.error.HTTPError(
                "https://pypi.org/pypi/justdocs/1.2.3/json",
                500,
                "server error",
                None,
                None,
            )
            with (
                patch.object(
                    checker.urllib.request,
                    "urlopen",
                    side_effect=server_error,
                ),
                self.assertRaisesRegex(
                    checker.PyPIArtifactError,
                    "PyPI query failed with HTTP 500",
                ),
            ):
                checker.publication_state("justdocs", "1.2.3", artifacts)

    def test_release_verification_rejects_invalid_polling_bounds(self) -> None:
        for option in ("--interval-seconds", "--timeout-seconds"):
            with self.subTest(option=option):
                completed = subprocess.run(
                    (
                        sys.executable,
                        "scripts/release/verify-pypi.py",
                        "--package",
                        "justdocs",
                        "--version",
                        "0.1.0",
                        option,
                        "0",
                    ),
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                self.assertEqual(2, completed.returncode)
                self.assertIn("must be a positive finite number", completed.stderr)

    @unittest.skipIf(os.name == "nt", "Bash release helper path")
    def test_release_versioning_orders_pep440_tags(self) -> None:
        versioning_script = Path("scripts/release/release-versioning.sh").resolve()
        with TemporaryDirectory() as directory:
            fake_git = Path(directory) / "git"
            fake_git.write_text(
                "#!/bin/sh\nprintf '%s\\n' v1.0.0 v1.1.0rc1 invalid v1.0.1 "
                "v1.1 v1.1.0 v1.1.0.0 v1.1.0.post1\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            env = os.environ | {
                "PYTHON_BIN": sys.executable,
                "PATH": os.pathsep.join(
                    (directory, str(Path(sys.executable).parent), os.environ["PATH"])
                ),
            }
            completed = subprocess.run(
                (
                    "bash",
                    "-c",
                    'source "$1"; latest_release_tag; previous_release_tag v1.1.0',
                    "bash",
                    str(versioning_script),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(["v1.1.0.post1", "v1.1.0rc1"], completed.stdout.splitlines())

    def test_release_versioning_uses_bash_32_constructs(self) -> None:
        script = Path("scripts/release/release-versioning.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("local -n", script)
        self.assertNotRegex(script, r"\b(?:mapfile|readarray)\b")

    @unittest.skipIf(os.name == "nt", "Bash release helper path")
    def test_release_versioning_propagates_python_failure(self) -> None:
        versioning_script = Path("scripts/release/release-versioning.sh").resolve()
        with TemporaryDirectory() as directory:
            failing_python = Path(directory) / "python-fails"
            failing_python.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
            failing_python.chmod(0o755)
            completed = subprocess.run(
                (
                    "bash",
                    "-c",
                    'source "$1"; latest_release_tag',
                    "bash",
                    str(versioning_script),
                ),
                check=False,
                env=os.environ | {"PYTHON_BIN": str(failing_python)},
                text=True,
                capture_output=True,
            )
        self.assertEqual(23, completed.returncode)
        self.assertEqual("", completed.stdout)

    @unittest.skipIf(os.name == "nt", "Bash release helper path")
    def test_release_versioning_rejects_missing_python(self) -> None:
        versioning_script = Path("scripts/release/release-versioning.sh").resolve()
        with TemporaryDirectory() as directory:
            missing_python = Path(directory) / "missing-python"
            completed = subprocess.run(
                (
                    "bash",
                    "-c",
                    'source "$1"; latest_release_tag',
                    "bash",
                    str(versioning_script),
                ),
                check=False,
                env=os.environ | {"PYTHON_BIN": str(missing_python)},
                text=True,
                capture_output=True,
            )
        self.assertEqual(127, completed.returncode)
        self.assertIn(
            f"Python executable not found: {missing_python}", completed.stderr
        )

    @unittest.skipIf(os.name == "nt", "POSIX Git release preparation path")
    def test_create_next_release_applies_initial_major_bump_without_artifacts(self) -> None:
        script = Path("scripts/release/create-next-release.py").resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            remote = root / "origin.git"
            repository.mkdir()
            subprocess.run(
                ("git", "init", "--initial-branch=main"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "config", "user.name", "Release Test"),
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ("git", "config", "user.email", "release@example.invalid"),
                cwd=repository,
                check=True,
            )
            (repository / "pyproject.toml").write_text(
                '[project]\nname = "justdocs"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (repository / "CHANGELOG.md").write_text(
                "# justdocs Changelog\n\nStable history.\n\n"
                "## Unreleased\n\n- Initial stable package.\n",
                encoding="utf-8",
            )
            (repository / ".gitignore").write_text(
                "artifacts/\n",
                encoding="utf-8",
            )
            subprocess.run(
                ("git", "add", "."), cwd=repository, check=True, capture_output=True
            )
            subprocess.run(
                ("git", "commit", "-m", "feat: initial package"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "init", "--bare", str(remote)),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "symbolic-ref", "HEAD", "refs/heads/main"),
                cwd=remote,
                check=True,
            )
            subprocess.run(
                ("git", "remote", "add", "origin", str(remote)),
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ("git", "push", "--set-upstream", "origin", "main"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "remote", "set-head", "origin", "--auto"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "tag", "latest"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            (repository / "moving-latest.txt").write_text(
                "moving release\n",
                encoding="utf-8",
            )
            subprocess.run(
                ("git", "add", "moving-latest.txt"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "commit", "-m", "feat: advance moving release"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ("git", "push", "origin", "main", "HEAD:refs/tags/latest"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            completed = subprocess.run(
                (
                    sys.executable,
                    str(script),
                    "--bump",
                    "major",
                    "--release-date",
                    "2026-07-12",
                ),
                cwd=repository,
                env=os.environ
                | {
                    "PYTHON_BIN": sys.executable,
                    "RELEASE_REPOSITORY_URL": (
                        "https://github.com/FanaticPythoner/justdocs"
                    ),
                },
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                "release: v1.0.0",
                subprocess.run(
                    ("git", "log", "-1", "--format=%s"),
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip(),
            )
            self.assertEqual(
                ["latest", "v1.0.0"],
                subprocess.run(
                    ("git", "tag", "--list"),
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.splitlines(),
            )
            changelog = (repository / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## Unreleased\n\n## v1.0.0 - 2026-07-12", changelog)
            self.assertIn("- Initial stable package.", changelog)
            self.assertIn("feat: initial package", changelog)
            self.assertIn(
                'version = "1.0.0"',
                (repository / "pyproject.toml").read_text(encoding="utf-8"),
            )
            self.assertFalse((repository / "artifacts").exists())
            self.assertEqual(
                ["latest"],
                subprocess.run(
                    ("git", "--git-dir", str(remote), "tag", "--list"),
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.splitlines(),
            )
            subprocess.run(
                ("git", "push", "origin", "main", "v1.0.0"),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            completed = subprocess.run(
                (
                    sys.executable,
                    str(script),
                    "--",
                    "--bump",
                    "patch",
                    "--release-date",
                    "2026-07-13",
                ),
                cwd=repository,
                env=os.environ
                | {
                    "PYTHON_BIN": sys.executable,
                    "RELEASE_REPOSITORY_URL": (
                        "https://github.com/FanaticPythoner/justdocs"
                    ),
                },
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn(
                'version = "1.0.1"',
                (repository / "pyproject.toml").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                ["latest", "v1.0.0", "v1.0.1"],
                subprocess.run(
                    ("git", "tag", "--list", "--sort=v:refname"),
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.splitlines(),
            )
            self.assertFalse((repository / "artifacts").exists())

    def test_pr_distribution_comment_renders_bound_artifact_metadata(self) -> None:
        path = Path("scripts/ci/sync-pr-python-dist-comment.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "sync_pr_python_dist_comment_test",
            path,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        try:
            specification.loader.exec_module(module)
        finally:
            sys.modules.pop(specification.name, None)
        context = module.RunContext(
            run_id=42,
            run_attempt=2,
            pull_request=137,
            head_sha="a" * 40,
            conclusion="success",
            html_url="https://github.com/FanaticPythoner/justdocs/actions/runs/42",
        )
        artifact = module.Artifact(
            artifact_id=73,
            size=4096,
            digest=f"sha256:{'b' * 64}",
            expires_at="2026-10-10T00:00:00Z",
        )
        with patch.dict(
            os.environ,
            {"GITHUB_REPOSITORY": "FanaticPythoner/justdocs"},
        ):
            body = module._render(context, artifact)
        self.assertIn(module.COMMENT_MARKER, body)
        self.assertIn("PR Python distributions: ready", body)
        self.assertIn("/actions/runs/42/artifacts/73", body)
        self.assertIn(artifact.digest, body)
        self.assertIn("unreviewed pull-request code", body)

    def test_pr_distribution_comment_binds_event_artifact_and_bot_comment(self) -> None:
        path = Path("scripts/ci/sync-pr-python-dist-comment.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "sync_pr_python_dist_comment_api_test",
            path,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        try:
            specification.loader.exec_module(module)
        finally:
            sys.modules.pop(specification.name, None)
        with TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "workflow_run": {
                            "id": 42,
                            "run_attempt": 3,
                            "name": "CI",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "a" * 40,
                            "html_url": (
                                "https://github.com/FanaticPythoner/justdocs/"
                                "actions/runs/42"
                            ),
                            "pull_requests": [{"number": 137}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"GITHUB_REPOSITORY": "FanaticPythoner/justdocs"},
            ):
                context = module._load_context(event_path)

        class FakeClient:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, object]] = []

            def request(
                self,
                method: str,
                endpoint: str,
                payload: object = None,
            ) -> object:
                self.requests.append((method, endpoint, payload))
                if endpoint.startswith("actions/runs/"):
                    return {
                        "artifacts": [
                            {
                                "id": 73,
                                "name": module.ARTIFACT_NAME,
                                "expired": False,
                                "size_in_bytes": 4096,
                                "digest": f"sha256:{'b' * 64}",
                                "expires_at": "2026-10-10T00:00:00Z",
                            }
                        ]
                    }
                if endpoint.startswith("issues/137/comments?"):
                    return [
                        {
                            "id": 80,
                            "body": module.COMMENT_MARKER,
                            "user": {"login": "attacker", "type": "User"},
                        },
                        {
                            "id": 81,
                            "body": (
                                f"{module.COMMENT_MARKER}\nrun-id: 41\n"
                                f"run-attempt: 1\nhead-sha: {'c' * 40}\n-->"
                            ),
                            "user": {
                                "login": "github-actions[bot]",
                                "type": "Bot",
                            },
                        },
                    ]
                return {"id": 81}

        client = FakeClient()
        artifact = module._artifact(client, context)
        with patch.dict(
            os.environ,
            {"GITHUB_REPOSITORY": "FanaticPythoner/justdocs"},
        ):
            body = module._render(context, artifact)
        module._synchronize(client, context, body)
        self.assertIn(
            ("PATCH", "issues/comments/81", {"body": body}),
            client.requests,
        )
        self.assertNotIn(
            ("PATCH", "issues/comments/80", {"body": body}),
            client.requests,
        )
        self.assertIn(("DELETE", "actions/artifacts/73", None), client.requests)

    def test_pr_distribution_close_removes_artifact_and_terminates_comment(self) -> None:
        path = Path("scripts/ci/sync-pr-python-dist-comment.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "sync_pr_python_dist_close_test",
            path,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        try:
            specification.loader.exec_module(module)
        finally:
            sys.modules.pop(specification.name, None)

        class FakeClient:
            repository = "FanaticPythoner/justdocs"

            def __init__(self) -> None:
                self.requests: list[tuple[str, str, object]] = []

            def request(
                self,
                method: str,
                endpoint: str,
                payload: object = None,
            ) -> object:
                self.requests.append((method, endpoint, payload))
                if endpoint == "pulls/137":
                    return {
                        "number": 137,
                        "state": "closed",
                        "head": {"sha": "a" * 40},
                        "base": {"repo": {"full_name": self.repository}},
                    }
                if endpoint.startswith("issues/137/comments?"):
                    return [
                        {
                            "id": 81,
                            "body": (
                                f"{module.COMMENT_MARKER}\nrun-id: 42\n"
                                f"run-attempt: 1\nhead-sha: {'a' * 40}\n-->"
                            ),
                            "user": {
                                "login": "github-actions[bot]",
                                "type": "Bot",
                            },
                        }
                    ]
                if endpoint == "actions/runs/42/artifacts?per_page=100":
                    return {
                        "artifacts": [
                            {"id": 73, "name": module.ARTIFACT_NAME},
                            {"id": 74, "name": "unrelated"},
                        ]
                    }
                return None

        client = FakeClient()
        module._close(client, 137, "a" * 40)
        self.assertIn(("DELETE", "actions/artifacts/73", None), client.requests)
        self.assertNotIn(("DELETE", "actions/artifacts/74", None), client.requests)
        patches = [request for request in client.requests if request[0] == "PATCH"]
        self.assertEqual(1, len(patches))
        self.assertIn("was removed when the pull request closed", patches[0][2]["body"])

    def test_github_release_verifier_matches_exact_local_asset_digests(self) -> None:
        path = Path("scripts/release/verify-github-release.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "verify_github_release_test",
            path,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            asset = Path(directory) / "justdocs-0.1.0-py3-none-any.whl"
            asset.write_bytes(b"distribution")
            local = module._local_assets(Path(directory))
        size, digest = local[asset.name]
        remote = module._remote_assets(
            {
                "assets": [
                    {
                        "name": asset.name,
                        "size": size,
                        "digest": digest,
                        "state": "uploaded",
                    }
                ]
            }
        )
        self.assertEqual(local, remote)

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_upload_curl_sends_exact_zero_and_nonzero_lengths(self) -> None:
        module = load_release_transaction_module()
        for payload in (b"", b"wire payload"):
            with self.subTest(size=len(payload)), TemporaryDirectory() as directory:
                path = Path(directory) / "asset.bin"
                path.write_bytes(payload)
                records: list[dict[str, object]] = []

                class UploadHandler(http.server.BaseHTTPRequestHandler):
                    def do_POST(self) -> None:
                        content_length = self.headers.get("Content-Length")
                        body = self.rfile.read(int(content_length or "0"))
                        records.append(
                            {
                                "content_length": content_length,
                                "transfer_encoding": self.headers.get(
                                    "Transfer-Encoding"
                                ),
                                "authorization": self.headers.get("Authorization"),
                                "body": body,
                            }
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b"{}")

                    def log_message(self, *_args: object) -> None:
                        return

                server = http.server.HTTPServer(("127.0.0.1", 0), UploadHandler)
                worker = threading.Thread(target=server.handle_request)
                worker.start()
                try:
                    with patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}):
                        completed = module._run_curl_with_regular_input(
                            (
                                "curl",
                                "--disable",
                                "--fail-with-body",
                                "--silent",
                                "--show-error",
                                "--proto",
                                "=http",
                                "--request",
                                "POST",
                                "-H",
                                "Content-Type: application/octet-stream",
                                "--data-binary",
                                "@-",
                                f"http://127.0.0.1:{server.server_port}/upload",
                            ),
                            path,
                        )
                finally:
                    worker.join(5)
                    server.server_close()
                self.assertEqual("{}", completed.stdout)
                self.assertEqual(
                    [
                        {
                            "content_length": str(len(payload)),
                            "transfer_encoding": None,
                            "authorization": "Bearer fixture-token",
                            "body": payload,
                        }
                    ],
                    records,
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_json_curl_sends_exact_zero_and_nonzero_lengths(self) -> None:
        module = load_release_transaction_module()
        for payload in (b"", b'{"draft":false}\n'):
            with self.subTest(size=len(payload)):
                records: list[dict[str, object]] = []

                class PatchHandler(http.server.BaseHTTPRequestHandler):
                    def do_PATCH(self) -> None:
                        content_length = self.headers.get("Content-Length")
                        body = self.rfile.read(int(content_length or "0"))
                        records.append(
                            {
                                "content_length": content_length,
                                "transfer_encoding": self.headers.get(
                                    "Transfer-Encoding"
                                ),
                                "authorization": self.headers.get("Authorization"),
                                "body": body,
                            }
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b"{}")

                    def log_message(self, *_args: object) -> None:
                        return

                server = http.server.HTTPServer(("127.0.0.1", 0), PatchHandler)
                worker = threading.Thread(target=server.handle_request)
                worker.start()
                try:
                    with patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}):
                        completed = module._run_curl_with_bytes_input(
                            (
                                "curl",
                                "--disable",
                                "--fail-with-body",
                                "--silent",
                                "--show-error",
                                "--proto",
                                "=http",
                                "--request",
                                "PATCH",
                                "-H",
                                "Content-Type: application/json",
                                "--data-binary",
                                "@-",
                                f"http://127.0.0.1:{server.server_port}/release",
                            ),
                            payload,
                        )
                finally:
                    worker.join(5)
                    server.server_close()
                self.assertEqual("{}", completed.stdout)
                self.assertEqual(
                    [
                        {
                            "content_length": str(len(payload)),
                            "transfer_encoding": None,
                            "authorization": "Bearer fixture-token",
                            "body": payload,
                        }
                    ],
                    records,
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_curl_rejects_unsafe_authorization_tokens(self) -> None:
        module = load_release_transaction_module()
        read_descriptor, write_descriptor = os.pipe()
        try:
            pipe_buffer = os.fpathconf(write_descriptor, "PC_PIPE_BUF")
        finally:
            os.close(read_descriptor)
            os.close(write_descriptor)
        arguments = (
            "curl",
            "--disable",
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--request",
            "PATCH",
            "--data-binary",
            "@-",
            "https://api.github.com/repos/FanaticPythoner/justdocs/releases/1",
        )
        for token in (
            "",
            "space token",
            "line\nbreak",
            "nonascii-é",
            "a" * pipe_buffer,
        ):
            with (
                self.subTest(token_length=len(token)),
                patch.dict(os.environ, {"GH_TOKEN": token}),
                self.assertRaises(module.ReleaseTransactionError),
            ):
                module._run_curl_with_bytes_input(arguments, b"{}")

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_preflight_rejects_transaction_root_substitution(self) -> None:
        module = load_release_transaction_module()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "runner-temp"
            displaced = root / "displaced-transaction"
            parent.mkdir()
            original_write = module._write_json_exclusive_at

            def write_then_substitute(
                directory_descriptor: int,
                name: str,
                payload: object,
            ) -> None:
                original_write(directory_descriptor, name, payload)
                created = next(parent.iterdir())
                created.rename(displaced)
                created.mkdir()

            with (
                patch.object(
                    module,
                    "_validate_preflight_inputs",
                    return_value="FanaticPythoner/justdocs",
                ),
                patch.object(module, "_validate_target_sha", return_value="2" * 40),
                patch.object(module, "_resolve_commit", return_value="2" * 40),
                patch.object(module, "_query_release_by_tag", return_value=None),
                patch.object(module, "_assert_no_detached_transaction_residue"),
                patch.object(module, "_validate_upload_transport"),
                patch.object(
                    module,
                    "_write_json_exclusive_at",
                    side_effect=write_then_substitute,
                ),
                self.assertRaisesRegex(
                    module.ReleaseTransactionError,
                    "created directory changed after binding",
                ),
            ):
                module._preflight("latest", str(parent), "false", "2" * 40)
            replacement = next(parent.iterdir())
            self.assertTrue(replacement.is_dir())
            self.assertEqual([], list(replacement.iterdir()))
            self.assertTrue((displaced / "transaction.json").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_immutable_exact_noop_and_mismatch_rejection(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        action = Path(".github/actions/release-assets/action.yml").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "replacement notes\n",
            )
            environment, gh_calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(
                        exists=True,
                        immutable=True,
                        assets={"package.whl": b"wheel"},
                    ),
                )
            )
            completed = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            transaction_root = Path(completed.stdout.strip())
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="Replacement release",
            )
            self.assertEqual(2, published.returncode)
            self.assertIn("is immutable and differs", published.stderr)
            gh_calls = release_transaction_calls(gh_calls_path)
            self.assertEqual([], release_transaction_mutations(gh_calls))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("preflight", journal["phase"])
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "original notes\n",
            )
            exact_assets = {path.name: path.read_bytes() for path in dist_dir.iterdir()}
            exact_state = transactional_release_state(
                exists=True,
                immutable=True,
                assets=exact_assets,
                asset_labels={name: "" for name in exact_assets},
            )
            environment, gh_calls_path, _, transaction_parent = (
                transactional_release_environment(root, exact_state)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="Original release",
            )
            self.assertEqual(0, published.returncode, published.stderr)
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(gh_calls_path)),
            )
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("committed", journal["phase"])
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )
        self.assertLess(
            action.index("- name: Verify staged inputs"),
            action.index("- name: Preflight release transaction"),
        )
        self.assertLess(
            action.index("- name: Preflight release transaction"),
            action.index("- name: Publish release transaction"),
        )
        self.assertNotIn("- name: Create or move tag", action)

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_rejects_preexisting_draft_before_mutation(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"replacement"},
                "replacement notes\n",
            )
            state = transactional_release_state(
                exists=True,
                assets={"package.whl": b"original"},
            )
            state["isDraft"] = True
            state["isLatest"] = False
            expected = release_state_projection(state)
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, state)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            rejected = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("preexisting draft releases are unsupported", rejected.stderr)
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(calls_path)),
            )
            current = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(expected, release_state_projection(current))
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("preflight", journal["phase"])
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_validates_operand_boundaries_before_github(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        invalid_operands = (
            ("-latest", "FanaticPythoner/justdocs", "false", TRANSACTION_TARGET_SHA),
            (
                "invalid tag",
                "FanaticPythoner/justdocs",
                "false",
                TRANSACTION_TARGET_SHA,
            ),
            ("latest", "owner/repo?query", "false", TRANSACTION_TARGET_SHA),
            ("latest", f"{'o' * 40}/repo", "false", TRANSACTION_TARGET_SHA),
            ("latest", f"owner/{'r' * 101}", "false", TRANSACTION_TARGET_SHA),
            ("latest", "FanaticPythoner/justdocs", "yes", TRANSACTION_TARGET_SHA),
            ("latest", "FanaticPythoner/justdocs", "false", "2" * 39),
        )
        for tag, repository, create_or_move_tag, target_sha in invalid_operands:
            with (
                self.subTest(
                    tag=tag,
                    repository=repository,
                    create_or_move_tag=create_or_move_tag,
                    target_sha=target_sha,
                ),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, gh_calls_path, _, transaction_parent = (
                    transactional_release_environment(
                        root, transactional_release_state(exists=False)
                    )
                )
                environment["GITHUB_REPOSITORY"] = repository
                completed = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                    tag=tag,
                    create_or_move_tag=create_or_move_tag,
                    target_sha=target_sha,
                )
                self.assertEqual(2, completed.returncode)
                self.assertEqual([], release_transaction_calls(gh_calls_path))
                self.assertEqual([], list(transaction_parent.iterdir()))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment, gh_calls_path, _, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(
                        exists=False,
                        tag_sha=TRANSACTION_ORIGINAL_SHA,
                    ),
                )
            )
            mismatched = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(2, mismatched.returncode)
            self.assertIn(
                "release tag does not target the release commit",
                mismatched.stderr,
            )
            self.assertEqual(
                2,
                len(release_transaction_calls(gh_calls_path)),
            )
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(gh_calls_path)),
            )
            self.assertEqual([], list(transaction_parent.iterdir()))

        for repository in (f"{'o' * 39}/repo", f"owner/{'r' * 100}"):
            with self.subTest(repository=repository), TemporaryDirectory() as directory:
                root = Path(directory)
                environment, gh_calls_path, _, transaction_parent = (
                    transactional_release_environment(
                        root, transactional_release_state(exists=False)
                    )
                )
                environment["GITHUB_REPOSITORY"] = repository
                completed = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(
                    ["api", "graphql"],
                    release_transaction_calls(gh_calls_path)[2][:2],
                )
                transaction_root = Path(completed.stdout.strip())
                cleanup_release_fixture(
                    transaction_script,
                    transaction_root,
                    transaction_parent,
                    environment,
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_rejects_release_race_tag_cas_and_nonmonotonic(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(
                exists=True,
                assets={"package.whl": b"wheel"},
            )
            environment, calls_path, _, transaction_parent = (
                transactional_release_environment(root, state)
            )
            environment["GH_MUTATE_RELEASE_ON_SECOND_QUERY"] = "1"
            raced = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(2, raced.returncode)
            self.assertIn("release changed during query", raced.stderr)
            self.assertEqual(
                [],
                [
                    call
                    for call in release_transaction_calls(calls_path)
                    if "-X" in call or "--method" in call
                ],
            )
            self.assertEqual([], list(transaction_parent.iterdir()))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(
                exists=True,
                assets={"package.whl": b"wheel"},
            )
            environment, _, _, transaction_parent = (
                transactional_release_environment(root, state)
            )
            environment["GH_TOGGLE_LATEST_ON_SECOND_QUERY"] = "1"
            stable = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, stable.returncode, stable.stderr)
            cleanup_release_fixture(
                transaction_script,
                Path(stable.stdout.strip()),
                transaction_parent,
                environment,
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(
                exists=False,
                tag_sha=TRANSACTION_ORIGINAL_SHA,
            )
            state["compareStatus"] = "behind"
            environment, calls_path, _, transaction_parent = (
                transactional_release_environment(root, state)
            )
            nonmonotonic = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(2, nonmonotonic.returncode)
            self.assertIn("latest release target is not monotonic", nonmonotonic.stderr)
            compare_calls = [
                call
                for call in release_transaction_calls(calls_path)
                if any("/compare/" in value for value in call)
            ]
            self.assertEqual(1, len(compare_calls))
            self.assertEqual([], list(transaction_parent.iterdir()))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"package.whl": b"old wheel"},
                tag_sha=TRANSACTION_ORIGINAL_SHA,
            )
            original_projection = release_state_projection(original)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            concurrent = json.loads(state_path.read_text(encoding="utf-8"))
            concurrent["tagSha"] = TRANSACTION_CONCURRENT_SHA
            state_path.write_text(
                json.dumps(concurrent, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            published = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "publish",
                    str(transaction_root),
                    "Replacement release",
                    "false",
                    str(notes_file),
                    str(dist_dir),
                    "true",
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, published.returncode)
            self.assertIn("remote release tag ownership changed", published.stderr)
            current = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original_projection, release_state_projection(current))
            self.assertEqual(TRANSACTION_CONCURRENT_SHA, current["tagSha"])
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("preflight", journal["phase"])
            self.assertEqual(
                [],
                [
                    call
                    for call in release_transaction_calls(calls_path)
                    if "-X" in call or "--method" in call
                ],
            )
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_absent_creates_draft_uploads_then_publishes(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {
                    "empty.bin": b"",
                    "package.tar.gz": b"source",
                    "package.whl": b"wheel",
                },
                "new release notes\n",
            )
            environment, gh_calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root, transactional_release_state(exists=False)
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            published = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "publish",
                    str(transaction_root),
                    "New release",
                    "false",
                    str(notes_file),
                    str(dist_dir),
                    "true",
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, published.returncode, published.stderr)
            calls = release_transaction_calls(gh_calls_path)
            marker = f"justdocs release transaction {transaction_root.name}"
            release_mutations = [
                call
                for call in calls
                if "-X" in call
                and any(
                    value.startswith("repos/FanaticPythoner/justdocs/releases")
                    for value in call
                )
                and not any("/assets/" in value for value in call)
            ]
            self.assertEqual(
                ["POST", "PATCH", "PATCH"],
                [call[call.index("-X") + 1] for call in release_mutations],
            )
            create_payload = json.loads(
                Path(
                    release_mutations[0][release_mutations[0].index("--input") + 1]
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                {
                    "body": marker,
                    "draft": True,
                    "make_latest": "false",
                    "name": marker,
                    "prerelease": False,
                    "tag_name": "latest",
                    "target_commitish": TRANSACTION_TARGET_SHA,
                },
                create_payload,
            )
            patch_payloads = [
                json.loads(
                    Path(call[call.index("--input") + 1]).read_text(encoding="utf-8")
                )
                for call in release_mutations[1:]
            ]
            self.assertEqual(
                [True, False], [value["draft"] for value in patch_payloads]
            )
            self.assertEqual(
                ["false", "legacy"],
                [value["make_latest"] for value in patch_payloads],
            )
            self.assertEqual(
                ["latest", "latest"],
                [value["tag_name"] for value in patch_payloads],
            )
            upload_calls = [
                call
                for call in calls
                if any(
                    value.startswith("https://uploads.github.com/") for value in call
                )
            ]
            uploaded_names = [
                value.split("name=", 1)[1].split("&", 1)[0]
                for call in upload_calls
                for value in call
                if value.startswith("https://uploads.github.com/")
            ]
            self.assertEqual(len(tuple(dist_dir.iterdir())), len(uploaded_names))
            self.assertEqual(len(uploaded_names), len(set(uploaded_names)))
            self.assertTrue(
                all(name.startswith("justdocs-upload-") for name in uploaded_names)
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["exists"])
            self.assertFalse(state["isDraft"])
            self.assertEqual("latest", state["releaseTag"])
            self.assertEqual("New release", state["name"])
            self.assertEqual("new release notes\n", state["description"])
            self.assertEqual(
                [state["databaseId"], state["databaseId"]],
                state["releaseMutationIds"],
            )
            for path in dist_dir.iterdir():
                asset = state["assets"][path.name]
                self.assertEqual(path.read_bytes().hex(), asset["hex"])
                self.assertEqual(path.stat().st_size, asset["size"])
                self.assertEqual(
                    f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                    asset["digest"],
                )
                self.assertEqual("", asset["label"])
                self.assertTrue(asset["content_type"])
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("committed", journal["phase"])
            self.assertIsNone(journal["original_release"])
            self.assertEqual(state["databaseId"], journal["created_release_id"])
            self.assertEqual(
                {name: asset["digest"] for name, asset in state["assets"].items()},
                journal["desired_asset_digests"],
            )
            self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_recovers_create_before_id_journal(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "new release notes\n",
            )
            environment, _, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_AFTER_CREATE"] = "1"
            crashed = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="New release",
            )
            self.assertEqual(-9, crashed.returncode)
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("mutating", journal["phase"])
            self.assertIsNone(journal["created_release_id"])
            self.assertEqual([], journal["precreate_release_ids"])
            self.assertTrue(journal["create_attempted"])
            orphan = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(orphan["exists"])
            self.assertTrue(orphan["isDraft"])
            self.assertTrue(orphan["releaseTag"].startswith("untagged-"))
            environment.pop("GH_CRASH_AFTER_CREATE")
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )
            recovered = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(recovered["exists"])

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_preserves_mutated_create_without_id(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "new release notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_AFTER_CREATE"] = "1"
            crashed = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="New release",
            )
            self.assertEqual(-9, crashed.returncode)
            environment.pop("GH_CRASH_AFTER_CREATE")
            mutated = json.loads(state_path.read_text(encoding="utf-8"))
            mutated["name"] = "External draft"
            mutated["description"] = "external notes\n"
            state_path.write_text(
                json.dumps(mutated, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            cleanup = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "cleanup",
                    str(transaction_root),
                    str(transaction_parent),
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, cleanup.returncode)
            self.assertIn("created release identity is indeterminate", cleanup.stderr)
            self.assertTrue(transaction_root.exists())
            preserved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(preserved["exists"])
            self.assertEqual("External draft", preserved["name"])
            self.assertEqual(
                [],
                [
                    call
                    for call in release_transaction_calls(calls_path)
                    if call[:3] == ["api", "-X", "DELETE"]
                ],
            )
            subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "cleanup",
                    str(stage_root),
                    str(stage_root.parent),
                ),
                check=True,
                text=True,
                capture_output=True,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_preflight_detects_detached_transaction_residue(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        marker = "justdocs release transaction justdocs-release-transaction-lost1234"

        def detached_state(kind: str) -> dict[str, object]:
            state = transactional_release_state(
                exists=True,
                assets={"package.whl": b"wheel"},
            )
            state["isDraft"] = True
            state["isLatest"] = False
            state["releaseTag"] = "untagged-lost-release"
            if kind == "marker":
                state["name"] = marker
                state["description"] = marker
            elif kind == "rollback":
                asset = state["assets"].pop("package.whl")
                state["assets"][f"justdocs-rollback-{asset['id']}"] = asset
            return state

        for kind, blocked in (
            ("marker", True),
            ("rollback", True),
            ("normal", False),
        ):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                root = Path(directory)
                environment, calls_path, _, transaction_parent = (
                    transactional_release_environment(root, detached_state(kind))
                )
                preflight = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                )
                if blocked:
                    self.assertEqual(2, preflight.returncode)
                    self.assertIn(
                        "detached GitHub release transaction residue detected",
                        preflight.stderr,
                    )
                    self.assertEqual([], list(transaction_parent.iterdir()))
                    self.assertEqual(
                        [],
                        release_transaction_mutations(
                            release_transaction_calls(calls_path)
                        ),
                    )
                else:
                    self.assertEqual(0, preflight.returncode, preflight.stderr)
                    cleanup_release_fixture(
                        transaction_script,
                        Path(preflight.stdout.strip()),
                        transaction_parent,
                        environment,
                    )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_preflight_detects_residue_with_tagged_release(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(exists=True)
            marker = (
                "justdocs release transaction justdocs-release-transaction-coexist1"
            )
            state["otherReleases"] = [
                {
                    "id": 1701,
                    "tag_name": "untagged-coexisting-release",
                    "immutable": False,
                    "draft": True,
                    "prerelease": False,
                    "name": marker,
                    "body": marker,
                    "assets": [],
                },
                {
                    "id": 1702,
                    "tag_name": "untagged-paginated-release",
                    "immutable": False,
                    "draft": True,
                    "prerelease": False,
                    "name": "External draft",
                    "body": "external notes\n",
                    "assets": [],
                    "fullAssets": [
                        {
                            "id": 1801,
                            "name": "justdocs-rollback-1801",
                            "label": None,
                            "content_type": "application/octet-stream",
                            "size": 5,
                            "digest": (
                                "sha256:" + hashlib.sha256(b"wheel").hexdigest()
                            ),
                            "state": "uploaded",
                        }
                    ],
                },
            ]
            environment, calls_path, _, transaction_parent = (
                transactional_release_environment(root, state)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(2, preflight.returncode)
            self.assertIn(
                "detached GitHub release transaction residue detected: 1701, 1702",
                preflight.stderr,
            )
            self.assertEqual([], list(transaction_parent.iterdir()))
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(calls_path)),
            )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(exists=True)
            orphan = legacy_other_release()
            target_names = (
                "install.ps1",
                "install.sh",
                "justdocs-0.1.0-py3-none-any.whl",
                "justdocs-0.1.0.tar.gz",
                "SHA256SUMS.txt",
            )
            orphan["fullAssets"] = [
                asset | {"name": target_name}
                for asset, target_name in zip(
                    orphan["fullAssets"],
                    target_names,
                    strict=True,
                )
            ]
            orphan["assets"] = orphan["fullAssets"]
            state["otherReleases"] = [orphan]
            environment, calls_path, _, _ = transactional_release_environment(
                root,
                state,
            )
            blocked = run_release_recover_detached(transaction_script, environment)
            self.assertEqual(2, blocked.returncode)
            self.assertIn("transaction residue detected", blocked.stderr)
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(calls_path)),
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_detached_latest_recovery_converges_from_each_state(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        expected_names = {
            "SHA256SUMS.txt",
            "install.ps1",
            "install.sh",
            "justdocs-0.1.0-py3-none-any.whl",
            "justdocs-0.1.0.tar.gz",
        }
        for progress in range(6):
            with self.subTest(progress=progress), TemporaryDirectory() as directory:
                root = Path(directory)
                original = legacy_detached_release_state(progress=progress)
                original_ids = {asset["id"] for asset in original["assets"].values()}
                original_name = original["name"]
                original_description = original["description"]
                environment, calls_path, state_path, _ = (
                    transactional_release_environment(root, original)
                )
                recovered = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                self.assertEqual(0, recovered.returncode, recovered.stderr)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertFalse(state["isDraft"])
                self.assertFalse(state["isLatest"])
                self.assertTrue(state["isPrerelease"])
                self.assertEqual("latest", state["releaseTag"])
                self.assertEqual(original_name, state["name"])
                self.assertEqual(original_description, state["description"])
                self.assertEqual(expected_names, set(state["assets"]))
                self.assertEqual(
                    original_ids,
                    {asset["id"] for asset in state["assets"].values()},
                )
                calls = release_transaction_calls(calls_path)
                mutations = release_transaction_mutations(calls)
                asset_patches = [
                    call
                    for call in mutations
                    if call[:3] == ["api", "-X", "PATCH"]
                    and any("/releases/assets/" in value for value in call)
                ]
                release_patches = [
                    call
                    for call in mutations
                    if call[:2] == ["--disable", "--fail-with-body"]
                    and "--request" in call
                    and call[call.index("--request") + 1] == "PATCH"
                    and call[-1].startswith("https://api.github.com/")
                ]
                self.assertEqual(5 - progress, len(asset_patches))
                self.assertEqual(1, len(release_patches))
                self.assertFalse(
                    any(
                        call[:3] == ["api", "-X", "PATCH"]
                        and "--input" in call
                        and call[call.index("--input") + 1] == "-"
                        for call in calls
                    )
                )
                mutation_count = len(mutations)
                rerun = run_release_recover_detached(transaction_script, environment)
                self.assertEqual(0, rerun.returncode, rerun.stderr)
                self.assertEqual(
                    mutation_count,
                    len(
                        release_transaction_mutations(
                            release_transaction_calls(calls_path)
                        )
                    ),
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_detached_latest_recovery_survives_every_crash_boundary(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        for rename_count in range(1, 6):
            with (
                self.subTest(boundary=f"rename-{rename_count}"),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, _, state_path, _ = transactional_release_environment(
                    root,
                    legacy_detached_release_state(),
                )
                environment["GH_CRASH_AFTER_ASSET_RENAME_COUNT"] = str(rename_count)
                crashed = run_release_recover_detached(transaction_script, environment)
                self.assertLess(crashed.returncode, 0)
                del environment["GH_CRASH_AFTER_ASSET_RENAME_COUNT"]
                retry = run_release_recover_detached(transaction_script, environment)
                self.assertEqual(0, retry.returncode, retry.stderr)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual("latest", state["releaseTag"])
                self.assertFalse(state["isDraft"])

        for failure_variable in (
            "GH_CRASH_AFTER_PUBLISH_PATCH",
            "GH_FAIL_AFTER_PUBLISH_PATCH",
        ):
            with (
                self.subTest(boundary=failure_variable),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, calls_path, state_path, _ = (
                    transactional_release_environment(
                        root,
                        legacy_detached_release_state(progress=5),
                    )
                )
                environment[failure_variable] = "1"
                interrupted = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                if failure_variable.startswith("GH_CRASH"):
                    self.assertLess(interrupted.returncode, 0)
                    del environment[failure_variable]
                    retry = run_release_recover_detached(
                        transaction_script,
                        environment,
                    )
                    self.assertEqual(0, retry.returncode, retry.stderr)
                else:
                    self.assertEqual(0, interrupted.returncode, interrupted.stderr)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual("latest", state["releaseTag"])
                self.assertFalse(state["isDraft"])
                self.assertEqual(
                    1,
                    len(
                        [
                            call
                            for call in release_transaction_mutations(
                                release_transaction_calls(calls_path)
                            )
                            if call[:2] == ["--disable", "--fail-with-body"]
                            and call[-1].startswith("https://api.github.com/")
                        ]
                    ),
                )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment, _, state_path, _ = transactional_release_environment(
                root,
                legacy_detached_release_state(),
            )
            environment["GH_FAIL_AFTER_ASSET_RENAME_COUNT"] = "1"
            recovered = run_release_recover_detached(transaction_script, environment)
            self.assertEqual(0, recovered.returncode, recovered.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("latest", state["releaseTag"])
            self.assertFalse(state["isDraft"])

        for failure_variable, progress in (
            ("GH_FAIL_BEFORE_ASSET_RENAME_COUNT", 0),
            ("GH_FAIL_BEFORE_PUBLISH_PATCH", 5),
        ):
            with (
                self.subTest(boundary=failure_variable),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, _, state_path, _ = transactional_release_environment(
                    root,
                    legacy_detached_release_state(progress=progress),
                )
                environment[failure_variable] = "1"
                failed = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                self.assertEqual(2, failed.returncode)
                del environment[failure_variable]
                retry = run_release_recover_detached(transaction_script, environment)
                self.assertEqual(0, retry.returncode, retry.stderr)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual("latest", state["releaseTag"])
                self.assertFalse(state["isDraft"])

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_detached_latest_recovery_noops_for_bound_release_and_checks_residue(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        for state_name, state in (
            ("arbitrary", transactional_release_state(exists=True)),
            ("terminal", legacy_detached_release_state(terminal=True)),
        ):
            with self.subTest(state=state_name), TemporaryDirectory() as directory:
                root = Path(directory)
                environment, calls_path, _, _ = transactional_release_environment(
                    root,
                    state,
                )
                recovered = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                self.assertEqual(0, recovered.returncode, recovered.stderr)
                self.assertEqual(
                    [],
                    release_transaction_mutations(
                        release_transaction_calls(calls_path)
                    ),
                )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = transactional_release_state(exists=True)
            marker = "justdocs release transaction justdocs-release-transaction-bound1"
            state["otherReleases"] = [
                {
                    "id": 1701,
                    "tag_name": "untagged-coexisting-release",
                    "immutable": False,
                    "draft": True,
                    "prerelease": False,
                    "name": marker,
                    "body": marker,
                    "assets": [],
                }
            ]
            environment, calls_path, _, _ = transactional_release_environment(
                root,
                state,
            )
            blocked = run_release_recover_detached(transaction_script, environment)
            self.assertEqual(2, blocked.returncode)
            self.assertIn("transaction residue detected", blocked.stderr)
            self.assertEqual(
                [],
                release_transaction_mutations(release_transaction_calls(calls_path)),
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_detached_latest_recovery_rejects_invalid_profiles_without_mutation(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()

        def manifest_asset(state: dict[str, object]) -> dict[str, object]:
            return next(
                asset
                for asset in state["assets"].values()
                if b"install.ps1" in bytes.fromhex(asset["hex"])
            )

        scenarios: list[tuple[str, dict[str, object], dict[str, str]]] = []
        wrong_name = legacy_detached_release_state()
        wrong_name["name"] = "Latest Nightly Build (333333333333)"
        scenarios.append(("wrong-name", wrong_name, {}))

        wrong_body = legacy_detached_release_state()
        wrong_body["description"] = "# justdocs latest\n\n- branch: `other`\n"
        scenarios.append(("wrong-body", wrong_body, {}))

        wrong_target = legacy_detached_release_state()
        other_sha = TRANSACTION_CONCURRENT_SHA
        wrong_target["name"] = f"Latest Nightly Build ({other_sha[:12]})"
        wrong_target["description"] = (
            "# justdocs latest\n\n"
            "- branch: `main`\n"
            f"- target commit: [`{other_sha}`]"
            f"(https://github.com/FanaticPythoner/justdocs/commit/{other_sha})\n"
        )
        scenarios.append(("wrong-target", wrong_target, {}))

        nonself_rollback = legacy_detached_release_state()
        old_name, moved = next(iter(nonself_rollback["assets"].items()))
        del nonself_rollback["assets"][old_name]
        nonself_rollback["assets"][f"justdocs-rollback-{moved['id'] + 1}"] = moved
        scenarios.append(("nonself-rollback", nonself_rollback, {}))

        labeled = legacy_detached_release_state()
        next(iter(labeled["assets"].values()))["label"] = "unexpected"
        scenarios.append(("asset-label", labeled, {}))

        digest_mismatch = legacy_detached_release_state()
        next(iter(digest_mismatch["assets"].values()))["digest"] = "sha256:" + "f" * 64
        scenarios.append(("asset-digest", digest_mismatch, {}))

        byte_mismatch = legacy_detached_release_state()
        next(iter(byte_mismatch["assets"].values()))["hex"] += "00"
        scenarios.append(("asset-bytes", byte_mismatch, {}))

        malformed_manifest = legacy_detached_release_state()
        malformed = manifest_asset(malformed_manifest)
        malformed_payload = b"invalid manifest\n"
        malformed["hex"] = malformed_payload.hex()
        malformed["size"] = len(malformed_payload)
        malformed["digest"] = f"sha256:{hashlib.sha256(malformed_payload).hexdigest()}"
        scenarios.append(("malformed-manifest", malformed_manifest, {}))

        ambiguous_manifest = legacy_detached_release_state()
        ambiguous_assets = list(ambiguous_manifest["assets"].values())[:2]
        ambiguous_assets[1]["hex"] = ambiguous_assets[0]["hex"]
        ambiguous_assets[1]["size"] = ambiguous_assets[0]["size"]
        ambiguous_assets[1]["digest"] = ambiguous_assets[0]["digest"]
        scenarios.append(("ambiguous-manifest", ambiguous_manifest, {}))

        nonprefix = legacy_detached_release_state()
        second_name = tuple(nonprefix["assets"])[1]
        second = nonprefix["assets"].pop(second_name)
        nonprefix["assets"]["install.sh"] = second
        scenarios.append(("nonprefix-partial-rename", nonprefix, {}))

        duplicate = legacy_detached_release_state()
        duplicate["otherReleases"] = [legacy_other_release()]
        scenarios.append(("duplicate-candidates", duplicate, {}))

        concurrent = legacy_detached_release_state()
        scenarios.append(
            (
                "concurrent-metadata",
                concurrent,
                {"GH_MUTATE_ON_RELEASE_ID_QUERY_COUNT": "2"},
            )
        )

        wrong_author = legacy_detached_release_state()
        wrong_author["authorLogin"] = "external-user"
        scenarios.append(("release-author", wrong_author, {}))

        wrong_uploader = legacy_detached_release_state()
        next(iter(wrong_uploader["assets"].values()))["uploaderLogin"] = "external-user"
        scenarios.append(("asset-uploader", wrong_uploader, {}))

        for name, state, overrides in scenarios:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                environment, calls_path, _, _ = transactional_release_environment(
                    root,
                    state,
                )
                environment.update(overrides)
                rejected = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual(
                    [],
                    release_transaction_mutations(
                        release_transaction_calls(calls_path)
                    ),
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_detached_latest_recovery_validates_transport_and_scope_first(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        transport_scenarios = (
            ("old", {"GH_CURL_VERSION_RESPONSE": "curl 7.75.0 fixture"}),
            ("malformed", {"GH_CURL_VERSION_RESPONSE": "curl unknown"}),
            (
                "failed",
                {
                    "GH_CURL_VERSION_RESPONSE": "",
                    "GH_CURL_VERSION_EXIT": "127",
                },
            ),
        )
        for name, overrides in transport_scenarios:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                environment, calls_path, _, _ = transactional_release_environment(
                    root,
                    legacy_detached_release_state(),
                )
                environment.update(overrides)
                rejected = run_release_recover_detached(
                    transaction_script,
                    environment,
                )
                self.assertEqual(2, rejected.returncode)
                calls = release_transaction_calls(calls_path)
                self.assertEqual([["--disable", "--version"]], calls)
                self.assertEqual([], release_transaction_mutations(calls))

        for name, overrides in transport_scenarios:
            with (
                self.subTest(preflight=name),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, calls_path, _, transaction_parent = (
                    transactional_release_environment(
                        root,
                        transactional_release_state(exists=False),
                    )
                )
                environment.update(overrides)
                rejected = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                )
                self.assertEqual(2, rejected.returncode)
                self.assertEqual([], list(transaction_parent.iterdir()))
                self.assertEqual(
                    [],
                    release_transaction_mutations(
                        release_transaction_calls(calls_path)
                    ),
                )

        for tag, repository in (
            ("v0.1.0", "FanaticPythoner/justdocs"),
            ("latest", "ExternalOwner/justdocs"),
        ):
            with (
                self.subTest(tag=tag, repository=repository),
                TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment, calls_path, _, _ = transactional_release_environment(
                    root,
                    legacy_detached_release_state(),
                )
                environment["GITHUB_REPOSITORY"] = repository
                rejected = subprocess.run(
                    (
                        sys.executable,
                        str(transaction_script),
                        "recover-detached",
                        tag,
                    ),
                    check=False,
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(2, rejected.returncode)
                self.assertEqual([], release_transaction_calls(calls_path))

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_reserves_internal_asset_names(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        scenarios = (
            (
                "staged-rollback",
                {"justdocs-rollback-901": b"reserved"},
                transactional_release_state(exists=False),
            ),
            (
                "staged-upload",
                {f"justdocs-upload-{'a' * 32}": b"reserved"},
                transactional_release_state(exists=False),
            ),
            (
                "existing-rollback",
                {"package.whl": b"wheel"},
                transactional_release_state(
                    exists=True,
                    assets={"justdocs-rollback-901": b"reserved"},
                ),
            ),
            (
                "existing-upload",
                {"package.whl": b"wheel"},
                transactional_release_state(
                    exists=True,
                    assets={f"justdocs-upload-{'b' * 32}": b"reserved"},
                ),
            ),
        )
        for name, staged_assets, release_state in scenarios:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                stage_root, dist_dir, notes_file = stage_transaction_assets(
                    root,
                    staged_assets,
                    "release notes\n",
                )
                environment, calls_path, _, transaction_parent = (
                    transactional_release_environment(root, release_state)
                )
                preflight = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                )
                self.assertEqual(0, preflight.returncode, preflight.stderr)
                transaction_root = Path(preflight.stdout.strip())
                published = run_release_publish(
                    transaction_script,
                    environment,
                    transaction_root,
                    notes_file,
                    dist_dir,
                    release_name="Release",
                )
                self.assertEqual(2, published.returncode)
                self.assertIn(
                    "reserved release transaction asset name",
                    published.stderr,
                )
                self.assertEqual(
                    [],
                    release_transaction_mutations(
                        release_transaction_calls(calls_path)
                    ),
                )
                journal = json.loads(
                    (transaction_root / "transaction.json").read_text(encoding="utf-8")
                )
                self.assertEqual("preflight", journal["phase"])
                cleanup_release_fixture(
                    transaction_script,
                    transaction_root,
                    transaction_parent,
                    environment,
                    stage_root,
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_preflight_detects_lost_journal_after_final_asset_rename(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "new release notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_AFTER_ASSET_RENAME_COUNT"] = str(
                len(tuple(dist_dir.iterdir()))
            )
            crashed = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="New release",
            )
            self.assertEqual(-9, crashed.returncode)
            environment.pop("GH_CRASH_AFTER_ASSET_RENAME_COUNT")
            orphan = json.loads(state_path.read_text(encoding="utf-8"))
            marker = f"justdocs release transaction {transaction_root.name}"
            self.assertTrue(orphan["isDraft"])
            self.assertEqual(marker, orphan["name"])
            self.assertEqual(marker, orphan["description"])
            self.assertEqual(
                {path.name for path in dist_dir.iterdir()},
                set(orphan["assets"]),
            )
            self.assertFalse(
                any(
                    name.startswith(("justdocs-rollback-", "justdocs-upload-"))
                    for name in orphan["assets"]
                )
            )
            second_parent = root / "second-runner-temp"
            second_parent.mkdir()
            calls_before_retry = len(release_transaction_calls(calls_path))
            retry = run_release_preflight(
                transaction_script,
                environment,
                second_parent,
            )
            self.assertEqual(2, retry.returncode)
            self.assertIn(
                "detached GitHub release transaction residue detected",
                retry.stderr,
            )
            retry_calls = release_transaction_calls(calls_path)[calls_before_retry:]
            self.assertEqual([], release_transaction_mutations(retry_calls))
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_preserves_externally_published_created_draft(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "new release notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_AFTER_ASSET_RENAME_COUNT"] = "1"
            crashed = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="New release",
            )
            self.assertEqual(-9, crashed.returncode)
            environment.pop("GH_CRASH_AFTER_ASSET_RENAME_COUNT")
            external = json.loads(state_path.read_text(encoding="utf-8"))
            external["isDraft"] = False
            external["isLatest"] = True
            external["releaseTag"] = "latest"
            external["name"] = "External published release"
            external["description"] = "external notes\n"
            state_path.write_text(
                json.dumps(external, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            calls_before_cleanup = len(release_transaction_calls(calls_path))
            cleanup = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "cleanup",
                    str(transaction_root),
                    str(transaction_parent),
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, cleanup.returncode)
            self.assertIn("created release identity is indeterminate", cleanup.stderr)
            self.assertTrue(transaction_root.exists())
            cleanup_calls = release_transaction_calls(calls_path)[calls_before_cleanup:]
            self.assertEqual(
                [],
                [call for call in cleanup_calls if call[:3] == ["api", "-X", "DELETE"]],
            )
            preserved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(preserved["isDraft"])
            self.assertEqual("External published release", preserved["name"])
            subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "cleanup",
                    str(stage_root),
                    str(stage_root.parent),
                ),
                check=True,
                text=True,
                capture_output=True,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_preserves_externally_published_existing_draft(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"package.whl": b"old wheel"},
            )
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_PARTIAL_UPLOAD"] = "1"
            crashed = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="Replacement release",
            )
            self.assertEqual(-9, crashed.returncode)
            environment.pop("GH_CRASH_PARTIAL_UPLOAD")
            external = json.loads(state_path.read_text(encoding="utf-8"))
            external["isDraft"] = False
            external["isLatest"] = True
            external["releaseTag"] = "latest"
            external["name"] = "Replacement release"
            external["description"] = "replacement notes\n"
            state_path.write_text(
                json.dumps(external, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            calls_before_cleanup = len(release_transaction_calls(calls_path))
            cleanup = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "cleanup",
                    str(transaction_root),
                    str(transaction_parent),
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, cleanup.returncode)
            self.assertIn("release identity cannot be rolled back", cleanup.stderr)
            self.assertTrue(transaction_root.exists())
            cleanup_calls = release_transaction_calls(calls_path)[calls_before_cleanup:]
            self.assertEqual([], release_transaction_mutations(cleanup_calls))
            preserved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(preserved["isDraft"])
            self.assertEqual("Replacement release", preserved["name"])
            subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "cleanup",
                    str(stage_root),
                    str(stage_root.parent),
                ),
                check=True,
                text=True,
                capture_output=True,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_absent_creation_failures_recover_by_identity(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        scenarios = (
            ("create", {"GH_FAIL_CREATE": "1"}, "indeterminate-empty"),
            (
                "query",
                {"GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE": "1"},
                "recovered",
            ),
            (
                "external",
                {
                    "GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE": "1",
                    "GH_REPLACE_MARKER_WITH_EXTERNAL_DRAFT": "1",
                },
                "indeterminate-external",
            ),
        )
        for name, fault_environment, outcome in scenarios:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                stage_root, dist_dir, notes_file = stage_transaction_assets(
                    root,
                    {"package.whl": b"wheel"},
                    "new release notes\n",
                )
                environment, calls_path, state_path, transaction_parent = (
                    transactional_release_environment(
                        root,
                        transactional_release_state(exists=False),
                    )
                )
                preflight = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                )
                self.assertEqual(0, preflight.returncode, preflight.stderr)
                transaction_root = Path(preflight.stdout.strip())
                environment.update(fault_environment)
                published = subprocess.run(
                    (
                        sys.executable,
                        str(transaction_script),
                        "publish",
                        str(transaction_root),
                        "New release",
                        "false",
                        str(notes_file),
                        str(dist_dir),
                        "true",
                    ),
                    check=False,
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(2, published.returncode)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                journal = json.loads(
                    (transaction_root / "transaction.json").read_text(encoding="utf-8")
                )
                calls = release_transaction_calls(calls_path)
                delete_calls = [
                    call
                    for call in calls
                    if call[:3] == ["api", "-X", "DELETE"]
                    and any("/releases/" in value for value in call)
                    and not any("/assets/" in value for value in call)
                ]
                if outcome == "recovered":
                    self.assertIn("rollback completed", published.stderr)
                    self.assertFalse(state["exists"])
                    self.assertEqual("rolled_back", journal["phase"])
                    self.assertEqual(1, len(delete_calls))
                    if delete_calls:
                        self.assertTrue(
                            any(
                                value.endswith(f"/releases/{state['databaseId']}")
                                for value in delete_calls[0]
                            )
                        )
                    cleanup_release_fixture(
                        transaction_script,
                        transaction_root,
                        transaction_parent,
                        environment,
                        stage_root,
                    )
                else:
                    self.assertIn("rollback failed", published.stderr)
                    self.assertIn(
                        "created release identity is indeterminate",
                        published.stderr,
                    )
                    self.assertEqual(
                        outcome == "indeterminate-external",
                        state["exists"],
                    )
                    if outcome == "indeterminate-external":
                        self.assertTrue(state["isDraft"])
                        self.assertEqual("External draft", state["name"])
                        self.assertEqual("external notes\n", state["description"])
                    self.assertEqual("mutating", journal["phase"])
                    self.assertEqual([], delete_calls)
                    cleanup = subprocess.run(
                        (
                            sys.executable,
                            str(transaction_script),
                            "cleanup",
                            str(transaction_root),
                            str(transaction_parent),
                        ),
                        check=False,
                        env=environment,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(2, cleanup.returncode)
                    self.assertTrue(transaction_root.exists())
                    subprocess.run(
                        (
                            sys.executable,
                            "scripts/release/stage-release-inputs.py",
                            "cleanup",
                            str(stage_root),
                            str(stage_root.parent),
                        ),
                        check=True,
                        text=True,
                        capture_output=True,
                    )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_absent_tag_residue_converges_on_retry(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "release notes\n",
            )
            environment, _, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False, tag_sha=None),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            first_root = Path(preflight.stdout.strip())
            environment["GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE"] = "1"
            failed = run_release_publish(
                transaction_script,
                environment,
                first_root,
                notes_file,
                dist_dir,
                release_name="Latest release",
                prerelease="true",
            )
            self.assertEqual(2, failed.returncode)
            self.assertIn("rollback retained the target tag", failed.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(state["exists"])
            self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
            journal = json.loads(
                (first_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("rolled_back_with_tag", journal["phase"])
            environment.pop("GH_FAIL_FIRST_RELEASE_QUERY_AFTER_CREATE")
            subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "cleanup",
                    str(first_root),
                    str(transaction_parent),
                ),
                check=True,
                env=environment,
                text=True,
                capture_output=True,
            )

            retry = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, retry.returncode, retry.stderr)
            retry_root = Path(retry.stdout.strip())
            published = run_release_publish(
                transaction_script,
                environment,
                retry_root,
                notes_file,
                dist_dir,
                release_name="Latest release",
                prerelease="true",
            )
            self.assertEqual(0, published.returncode, published.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["exists"])
            self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
            cleanup_release_fixture(
                transaction_script,
                retry_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_existing_orders_backup_draft_replace_publish(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        original_assets = {
            "keep.bin": b"keep",
            "package.whl": b"old wheel",
        }
        for purge in (False, True):
            with self.subTest(purge=purge), TemporaryDirectory() as directory:
                root = Path(directory)
                stage_root, dist_dir, notes_file = stage_transaction_assets(
                    root,
                    {"package.tar.gz": b"source", "package.whl": b"new wheel"},
                    "replacement notes\n",
                )
                original = transactional_release_state(
                    exists=True,
                    assets=original_assets,
                    asset_labels={
                        "keep.bin": "Keep binary",
                        "package.whl": "Python wheel",
                    },
                    tag_sha=TRANSACTION_ORIGINAL_SHA,
                )
                environment, calls_path, state_path, transaction_parent = (
                    transactional_release_environment(
                        root,
                        original,
                    )
                )
                preflight = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                    create_or_move_tag="true",
                )
                self.assertEqual(0, preflight.returncode, preflight.stderr)
                transaction_root = Path(preflight.stdout.strip())
                published = subprocess.run(
                    (
                        sys.executable,
                        str(transaction_script),
                        "publish",
                        str(transaction_root),
                        "Replacement release",
                        "true",
                        str(notes_file),
                        str(dist_dir),
                        str(purge).lower(),
                    ),
                    check=False,
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, published.returncode, published.stderr)
                calls = release_transaction_calls(calls_path)
                download_indices = [
                    index
                    for index, call in enumerate(calls)
                    if any("/releases/assets/" in value for value in call)
                    and "Accept: application/octet-stream" in call
                ]
                asset_patch_indices = [
                    index
                    for index, call in enumerate(calls)
                    if call[:3] == ["api", "-X", "PATCH"]
                    and any("/releases/assets/" in value for value in call)
                ]
                retained_patch_indices = [
                    index
                    for index in asset_patch_indices
                    if any(
                        value.startswith("name=justdocs-rollback-")
                        for value in calls[index]
                    )
                ]
                uploaded_patch_indices = [
                    index
                    for index in asset_patch_indices
                    if index not in retained_patch_indices
                ]
                patch_indices = [
                    index
                    for index, call in enumerate(calls)
                    if call[:3] == ["api", "-X", "PATCH"]
                    and any(value.endswith("/releases/701") for value in call)
                ]
                delete_indices = [
                    index
                    for index, call in enumerate(calls)
                    if call[:3] == ["api", "--method", "DELETE"]
                ]
                upload_indices = [
                    index
                    for index, call in enumerate(calls)
                    if any(
                        value.startswith("https://uploads.github.com/")
                        for value in call
                    )
                ]
                self.assertEqual(0, len(download_indices))
                self.assertEqual(2, len(patch_indices))
                self.assertEqual(2 if purge else 1, len(retained_patch_indices))
                self.assertEqual(3, len(uploaded_patch_indices))
                self.assertEqual(2 if purge else 1, len(delete_indices))
                self.assertEqual(3, len(upload_indices))
                self.assertLess(patch_indices[0], min(retained_patch_indices))
                self.assertLess(max(retained_patch_indices), min(upload_indices))
                self.assertLess(max(upload_indices), min(uploaded_patch_indices))
                repository = "FanaticPythoner/justdocs"
                deleted_names = sorted(original_assets) if purge else ["package.whl"]
                self.assertEqual(
                    [
                        f"repos/{repository}/releases/assets/"
                        f"{original['assets'][name]['id']}"
                        for name in deleted_names
                    ],
                    [
                        next(
                            value
                            for value in calls[index]
                            if "/releases/assets/" in value
                        )
                        for index in retained_patch_indices
                    ],
                )
                self.assertEqual(
                    [
                        f"repos/{repository}/releases/assets/"
                        f"{original['assets'][name]['id']}"
                        for name in deleted_names
                    ],
                    [calls[index][-1] for index in delete_indices],
                )
                self.assertEqual(
                    ["@-"] * len(upload_indices),
                    [
                        calls[index][calls[index].index("--data-binary") + 1]
                        for index in upload_indices
                    ],
                )
                self.assertEqual(
                    [str(path.stat().st_size) for path in sorted(dist_dir.iterdir())],
                    [
                        next(
                            value.removeprefix("Content-Length: ")
                            for value in calls[index]
                            if value.startswith("Content-Length: ")
                        )
                        for index in upload_indices
                    ],
                )
                self.assertTrue(
                    all(
                        len(
                            [
                                value
                                for value in calls[index]
                                if value.startswith("Content-Length: ")
                            ]
                        )
                        == 1
                        for index in upload_indices
                    )
                )
                patch_payloads = [
                    json.loads(
                        Path(calls[index][calls[index].index("--input") + 1]).read_text(
                            encoding="utf-8"
                        )
                    )
                    for index in patch_indices
                ]
                self.assertEqual(
                    [
                        (
                            "latest",
                            f"justdocs release transaction {transaction_root.name}",
                            True,
                            False,
                            "false",
                        ),
                        ("latest", "Replacement release", False, True, "false"),
                    ],
                    [
                        (
                            payload["tag_name"],
                            payload["name"],
                            payload["draft"],
                            payload["prerelease"],
                            payload["make_latest"],
                        )
                        for payload in patch_payloads
                    ],
                )
                state = json.loads(state_path.read_text(encoding="utf-8"))
                expected_names = {path.name for path in dist_dir.iterdir()}
                if not purge:
                    expected_names.add("keep.bin")
                    self.assertEqual(
                        original["assets"]["keep.bin"],
                        state["assets"]["keep.bin"],
                    )
                self.assertEqual(expected_names, set(state["assets"]))
                for path in dist_dir.iterdir():
                    asset = state["assets"][path.name]
                    self.assertEqual(path.read_bytes().hex(), asset["hex"])
                    self.assertEqual(path.stat().st_size, asset["size"])
                    self.assertEqual(
                        f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                        asset["digest"],
                    )
                    self.assertEqual("", asset["label"])
                    self.assertTrue(asset["content_type"])
                self.assertFalse(state["isDraft"])
                self.assertTrue(state["isPrerelease"])
                self.assertFalse(state["isLatest"])
                self.assertEqual("Replacement release", state["name"])
                self.assertEqual("replacement notes\n", state["description"])
                journal = json.loads(
                    (transaction_root / "transaction.json").read_text(encoding="utf-8")
                )
                self.assertEqual("committed", journal["phase"])
                self.assertEqual(TRANSACTION_ORIGINAL_SHA, journal["original_tag_sha"])
                self.assertEqual(
                    {
                        name: {
                            key: asset[key]
                            for key in (
                                "id",
                                "name",
                                "label",
                                "content_type",
                                "size",
                                "digest",
                                "state",
                            )
                        }
                        for name, asset in {
                            name: record | {"name": name}
                            for name, record in original["assets"].items()
                        }.items()
                    },
                    {
                        asset["name"]: asset
                        for asset in journal["original_release"]["assets"]
                    },
                )
                tag_mutations = [
                    call
                    for call in calls
                    if call[:3] == ["api", "-X", "PATCH"]
                    and any("/git/refs/tags/" in value for value in call)
                ]
                self.assertEqual(1, len(tag_mutations))
                self.assertIn(f"sha={TRANSACTION_TARGET_SHA}", tag_mutations[0])
                tag_index = calls.index(tag_mutations[0])
                self.assertLess(max(upload_indices), tag_index)
                self.assertLess(max(uploaded_patch_indices), tag_index)
                self.assertLess(tag_index, min(delete_indices))
                self.assertLess(max(delete_indices), patch_indices[1])
                self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
                cleanup_release_fixture(
                    transaction_script,
                    transaction_root,
                    transaction_parent,
                    environment,
                    stage_root,
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_commits_forward_after_retained_asset_delete(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
                tag_sha=TRANSACTION_ORIGINAL_SHA,
            )
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_FAIL_AFTER_FIRST_ASSET_DELETE"] = "1"
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="Replacement release",
            )
            self.assertEqual(0, published.returncode, published.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["assetDeleteFailed"])
            self.assertFalse(state["isDraft"])
            self.assertEqual("Replacement release", state["name"])
            self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
            self.assertEqual(
                {path.name for path in dist_dir.iterdir()},
                set(state["assets"]),
            )
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("committed", journal["phase"])
            calls = release_transaction_calls(calls_path)
            tag_index = next(
                index
                for index, call in enumerate(calls)
                if any("/git/refs/tags/" in value for value in call) and "PATCH" in call
            )
            delete_indices = [
                index
                for index, call in enumerate(calls)
                if call[:3] == ["api", "--method", "DELETE"]
            ]
            publish_index = max(
                index
                for index, call in enumerate(calls)
                if call[:3] == ["api", "-X", "PATCH"]
                and any(value.endswith("/releases/701") for value in call)
            )
            self.assertLess(tag_index, min(delete_indices))
            self.assertLess(max(delete_indices), publish_index)
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_crash_boundaries_commit_forward(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        scenarios = (
            ("tag", {"GH_CRASH_AFTER_TAG_PATCH": "1"}, "tagging"),
            (
                "first-delete",
                {"GH_CRASH_ON_ASSET_DELETE_COUNT": "1"},
                "committing",
            ),
            (
                "all-deleted",
                {"GH_CRASH_ON_ASSET_DELETE_COUNT": "2"},
                "committing",
            ),
            (
                "published",
                {"GH_CRASH_AFTER_PUBLISH_PATCH": "1"},
                "committing",
            ),
        )
        for name, fault, expected_phase in scenarios:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                original = transactional_release_state(
                    exists=True,
                    assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
                    tag_sha=TRANSACTION_ORIGINAL_SHA,
                )
                original_ids = {asset["id"] for asset in original["assets"].values()}
                stage_root, dist_dir, notes_file = stage_transaction_assets(
                    root,
                    {"package.whl": b"new wheel"},
                    "replacement notes\n",
                )
                expected_asset_names = {path.name for path in dist_dir.iterdir()}
                environment, _, state_path, transaction_parent = (
                    transactional_release_environment(root, original)
                )
                preflight = run_release_preflight(
                    transaction_script,
                    environment,
                    transaction_parent,
                    create_or_move_tag="true",
                )
                self.assertEqual(0, preflight.returncode, preflight.stderr)
                transaction_root = Path(preflight.stdout.strip())
                environment.update(fault)
                interrupted = run_release_publish(
                    transaction_script,
                    environment,
                    transaction_root,
                    notes_file,
                    dist_dir,
                    release_name="Replacement release",
                )
                self.assertEqual(-9, interrupted.returncode)
                journal = json.loads(
                    (transaction_root / "transaction.json").read_text(encoding="utf-8")
                )
                self.assertEqual(expected_phase, journal["phase"])
                for key in fault:
                    environment.pop(key)
                cleanup_release_fixture(
                    transaction_script,
                    transaction_root,
                    transaction_parent,
                    environment,
                    stage_root,
                )
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertFalse(state["isDraft"])
                self.assertEqual("Replacement release", state["name"])
                self.assertEqual(TRANSACTION_TARGET_SHA, state["tagSha"])
                self.assertEqual(
                    expected_asset_names,
                    set(state["assets"]),
                )
                self.assertTrue(
                    original_ids.isdisjoint(
                        {asset["id"] for asset in state["assets"].values()}
                    )
                )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_partial_upload_restores_assets_and_state(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
                asset_labels={
                    "keep.bin": "Keep binary",
                    "package.whl": "Python wheel",
                },
                tag_sha=TRANSACTION_ORIGINAL_SHA,
            )
            original_projection = release_state_projection(original)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.tar.gz": b"source", "package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            environment["GH_FAIL_PARTIAL_UPLOAD"] = "1"
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            published = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "publish",
                    str(transaction_root),
                    "Replacement release",
                    "true",
                    str(notes_file),
                    str(dist_dir),
                    "true",
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, published.returncode)
            self.assertIn("rollback completed", published.stderr)
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original_projection, release_state_projection(restored))
            self.assertEqual(TRANSACTION_ORIGINAL_SHA, restored["tagSha"])
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("rolled_back", journal["phase"])
            calls = release_transaction_calls(calls_path)
            upload_indices = [
                index
                for index, call in enumerate(calls)
                if any(
                    value.startswith("https://uploads.github.com/") for value in call
                )
            ]
            rollback_patch_indices = [
                index
                for index, call in enumerate(calls)
                if call[:3] == ["api", "-X", "PATCH"]
                and any(value.endswith("/releases/701") for value in call)
            ]
            self.assertEqual(1, len(upload_indices))
            self.assertEqual(3, len(rollback_patch_indices))
            self.assertLess(upload_indices[0], rollback_patch_indices[-1])
            asset_renames = [
                call
                for call in calls
                if call[:3] == ["api", "-X", "PATCH"]
                and any("/releases/assets/" in value for value in call)
            ]
            self.assertEqual(4, len(asset_renames))
            self.assertEqual(
                {asset["id"] for asset in original["assets"].values()},
                {
                    int(value.rsplit("/", 1)[1])
                    for call in asset_renames
                    for value in call
                    if "/releases/assets/" in value
                },
            )
            self.assertEqual(
                1,
                len(
                    [
                        call
                        for call in calls
                        if call[:3] == ["api", "--method", "DELETE"]
                    ]
                ),
            )
            tag_mutations = [
                call
                for call in calls
                if call[:3] == ["api", "-X", "PATCH"]
                and any("/git/refs/tags/" in value for value in call)
            ]
            self.assertEqual([], tag_mutations)
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_deletes_owned_starter_after_upload_502(
        self,
    ) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
            )
            original_projection = release_state_projection(original)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_FAIL_UPLOAD_502_STARTER"] = "1"
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                purge_existing_assets="false",
            )
            self.assertEqual(2, published.returncode)
            self.assertIn("rollback completed", published.stderr)
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original_projection, release_state_projection(restored))
            starter_id = restored["starterAssetId"]
            self.assertIn(starter_id, restored["deletedAssetIds"])
            self.assertTrue(
                any(
                    value.endswith(f"/releases/assets/{starter_id}")
                    for call in release_transaction_calls(calls_path)
                    for value in call
                )
            )
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("rolled_back", journal["phase"])
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_noop_recovery_preserves_asset_ids(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
            )
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            environment["GH_CRASH_ON_TAG_RESOLVE_COUNT"] = "3"
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            interrupted = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
            )
            self.assertEqual(-9, interrupted.returncode)
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("mutating", journal["phase"])
            interrupted_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original["assets"], interrupted_state["assets"])
            self.assertEqual(
                [],
                [
                    call
                    for call in release_transaction_calls(calls_path)
                    if "-X" in call or "--method" in call
                ],
            )
            environment.pop("GH_CRASH_ON_TAG_RESOLVE_COUNT")
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original["assets"], restored["assets"])
            self.assertFalse(transaction_root.exists())

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_reconciles_successful_committing_phase(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"wheel"},
                "release notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(
                    root,
                    transactional_release_state(exists=False),
                )
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_FAIL_AFTER_PUBLISH_PATCH"] = "1"
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                release_name="Published release",
            )
            self.assertEqual(0, published.returncode, published.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["exists"])
            self.assertFalse(state["isDraft"])
            self.assertFalse(state["isLatest"])
            self.assertEqual("Published release", state["name"])
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("committed", journal["phase"])
            self.assertIsNotNone(journal["prepared_release"])
            self.assertEqual(
                [],
                [
                    call
                    for call in release_transaction_calls(calls_path)
                    if call[:3] == ["api", "-X", "DELETE"]
                    and any("/releases/" in value for value in call)
                ],
            )
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_refuses_unknown_concurrent_asset(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
            )
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_INJECT_UNKNOWN_ASSET_AFTER_UPLOAD"] = "1"
            published = run_release_publish(
                transaction_script,
                environment,
                transaction_root,
                notes_file,
                dist_dir,
                purge_existing_assets="false",
            )
            self.assertEqual(2, published.returncode)
            self.assertIn(
                "release asset ownership changed: external.bin", published.stderr
            )
            self.assertIn("rollback failed", published.stderr)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            external_id = state["assets"]["external.bin"]["id"]
            self.assertNotIn(external_id, state.get("deletedAssetIds", []))
            self.assertFalse(
                any(
                    value.endswith(f"/releases/assets/{external_id}")
                    for call in release_transaction_calls(calls_path)
                    for value in call
                )
            )
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("mutating", journal["phase"])
            cleanup = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "cleanup",
                    str(transaction_root),
                    str(transaction_parent),
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, cleanup.returncode)
            subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "cleanup",
                    str(stage_root),
                    str(stage_root.parent),
                ),
                check=True,
                text=True,
                capture_output=True,
            )

    @unittest.skipIf(os.name == "nt", "POSIX release transaction path")
    def test_release_transaction_cleanup_recovers_interrupted_mutation(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = transactional_release_state(
                exists=True,
                assets={"keep.bin": b"keep", "package.whl": b"old wheel"},
                asset_labels={
                    "keep.bin": "Keep binary",
                    "package.whl": "Python wheel",
                },
                tag_sha=TRANSACTION_ORIGINAL_SHA,
            )
            original_projection = release_state_projection(original)
            stage_root, dist_dir, notes_file = stage_transaction_assets(
                root,
                {"package.tar.gz": b"source", "package.whl": b"new wheel"},
                "replacement notes\n",
            )
            environment, calls_path, state_path, transaction_parent = (
                transactional_release_environment(root, original)
            )
            preflight = run_release_preflight(
                transaction_script,
                environment,
                transaction_parent,
                create_or_move_tag="true",
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            environment["GH_CRASH_PARTIAL_UPLOAD"] = "1"
            interrupted = subprocess.run(
                (
                    sys.executable,
                    str(transaction_script),
                    "publish",
                    str(transaction_root),
                    "Replacement release",
                    "true",
                    str(notes_file),
                    str(dist_dir),
                    "true",
                ),
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(-9, interrupted.returncode)
            journal = json.loads(
                (transaction_root / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("mutating", journal["phase"])
            self.assertIsNotNone(journal["original_release"])
            interrupted_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(
                original_projection,
                release_state_projection(interrupted_state),
            )
            self.assertTrue(interrupted_state["isDraft"])
            self.assertEqual(TRANSACTION_ORIGINAL_SHA, interrupted_state["tagSha"])
            environment.pop("GH_CRASH_PARTIAL_UPLOAD")
            cleanup_release_fixture(
                transaction_script,
                transaction_root,
                transaction_parent,
                environment,
                stage_root,
            )
            self.assertFalse(transaction_root.exists())
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(original_projection, release_state_projection(restored))
            self.assertEqual(TRANSACTION_ORIGINAL_SHA, restored["tagSha"])
            self.assertEqual(
                1,
                len(
                    [
                        call
                        for call in release_transaction_calls(calls_path)
                        if any(
                            value.startswith("https://uploads.github.com/")
                            for value in call
                        )
                    ]
                ),
            )

    @unittest.skipIf(os.name == "nt", "Bash composite action path")
    def test_release_action_cleanup_removes_transaction_and_snapshot(self) -> None:
        transaction_script = Path(
            "scripts/release/transactional-github-release.py"
        ).resolve()
        action = Path(".github/actions/release-assets/action.yml").read_text(
            encoding="utf-8"
        )
        cleanup_step = action.split(
            "    - name: Cleanup release transaction\n",
            1,
        )[1]
        cleanup_script = dedent(cleanup_step.split("      run: |\n", 1)[1])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment, _, _, runner_temp = transactional_release_environment(
                root,
                transactional_release_state(exists=False),
            )
            workspace = root / "action-workspace"
            dist = workspace / "release"
            dist.mkdir(parents=True)
            payload = b"wheel"
            (dist / "package.whl").write_bytes(payload)
            (dist / "SHA256SUMS.txt").write_text(
                f"{hashlib.sha256(payload).hexdigest()}  package.whl\n",
                encoding="utf-8",
            )
            staged = subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "stage",
                    str(dist),
                    "",
                    str(runner_temp),
                ),
                check=False,
                env=environment | {"GITHUB_WORKSPACE": str(workspace)},
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, staged.returncode, staged.stderr)
            stage_root = Path(staged.stdout.strip())
            preflight = run_release_preflight(
                transaction_script,
                environment,
                runner_temp,
            )
            self.assertEqual(0, preflight.returncode, preflight.stderr)
            transaction_root = Path(preflight.stdout.strip())
            cleanup_environment = environment | {
                "GH_TOKEN": "fixture-token",
                "RUNNER_TEMP": str(runner_temp),
                "STAGE_ROOT": str(stage_root),
                "TRANSACTION_ROOT": str(transaction_root),
            }
            cleaned = subprocess.run(
                ("bash", "-c", cleanup_script),
                check=False,
                env=cleanup_environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, cleaned.returncode, cleaned.stderr)
            self.assertFalse(stage_root.exists())
            cleaned_again = subprocess.run(
                ("bash", "-c", cleanup_script),
                check=False,
                env=cleanup_environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, cleaned_again.returncode, cleaned_again.stderr)
            self.assertFalse(transaction_root.exists())
            self.assertEqual([], list(runner_temp.iterdir()))

    @unittest.skipIf(os.name == "nt", "Bash composite action path")
    def test_release_action_rejects_invalid_inputs_before_mutation(self) -> None:
        action = Path(".github/actions/release-assets/action.yml").read_text(
            encoding="utf-8"
        )
        validate_step = action.split("    - name: Validate inputs\n", 1)[1].split(
            "\n    - name:", 1
        )[0]
        script = dedent(validate_step.split("      run: |\n", 1)[1])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dist_dir = root / "release"
            empty_dist_dir = root / "empty"
            directory_dist_dir = root / "directory-entry"
            fifo_dist_dir = root / "fifo-entry"
            symlink_dist_dir = root / "symlink-entry"
            symlinked_dist_dir = root / "symlinked-directory"
            unreadable_dist_dir = root / "unreadable-entry"
            runner_temp = root / "runner-temp"
            github_output = root / "github-output"
            dist_dir.mkdir()
            empty_dist_dir.mkdir()
            directory_dist_dir.mkdir()
            fifo_dist_dir.mkdir()
            symlink_dist_dir.mkdir()
            unreadable_dist_dir.mkdir()
            runner_temp.mkdir()
            github_output.write_text("", encoding="utf-8")
            asset_payload = b"wheel"
            asset_digest = hashlib.sha256(asset_payload).hexdigest()
            manifest = f"{asset_digest}  package.whl\n"
            (dist_dir / "package.whl").write_bytes(asset_payload)
            (dist_dir / "SHA256SUMS.txt").write_text(manifest, encoding="utf-8")
            (directory_dist_dir / "package.whl").mkdir()
            os.mkfifo(fifo_dist_dir / "package.whl")
            (symlink_dist_dir / "package.whl").symlink_to(dist_dir / "package.whl")
            symlinked_dist_dir.symlink_to(dist_dir, target_is_directory=True)
            unreadable_asset = unreadable_dist_dir / "package.whl"
            unreadable_asset.write_bytes(asset_payload)
            unreadable_asset.chmod(0)
            for invalid_dist_dir in (
                directory_dist_dir,
                fifo_dist_dir,
                symlink_dist_dir,
                unreadable_dist_dir,
            ):
                (invalid_dist_dir / "SHA256SUMS.txt").write_text(
                    manifest, encoding="utf-8"
                )
            notes_file = root / "notes.md"
            notes_file.write_text("release notes\n", encoding="utf-8")
            symlinked_notes_parent = root / "symlinked-notes-parent"
            symlinked_notes_parent.symlink_to(root, target_is_directory=True)
            valid_env = {
                "RELEASE_TAG": "latest",
                "RELEASE_NAME": "Latest",
                "PRERELEASE": "true",
                "PURGE_EXISTING_ASSETS": "true",
                "CREATE_OR_MOVE_TAG": "true",
                "DIST_DIR": str(dist_dir),
                "NOTES_FILE": str(notes_file),
                "GITHUB_OUTPUT": str(github_output),
                "GITHUB_WORKSPACE": str(root),
                "RUNNER_TEMP": str(runner_temp),
            }
            valid = subprocess.run(
                ("bash", "-c", script),
                check=False,
                env=os.environ | valid_env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, valid.returncode, valid.stderr)
            self.assertEqual("", valid.stderr)
            outputs = dict(
                line.split("=", 1)
                for line in github_output.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual({"stage_root", "dist_dir", "notes_file"}, set(outputs))
            stage_root = Path(outputs["stage_root"])
            self.assertEqual(runner_temp.resolve(), stage_root.parent)
            self.assertEqual(stage_root / "assets", Path(outputs["dist_dir"]))
            self.assertEqual(
                stage_root / "release-notes.md", Path(outputs["notes_file"])
            )
            snapshot_verified = subprocess.run(
                (
                    sys.executable,
                    "scripts/release/stage-release-inputs.py",
                    "verify",
                    str(stage_root),
                ),
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, snapshot_verified.returncode, snapshot_verified.stderr)

            invalid_cases = (
                ({"PRERELEASE": "TRUE"}, "invalid prerelease"),
                (
                    {"PURGE_EXISTING_ASSETS": "yes"},
                    "invalid purge_existing_assets",
                ),
                (
                    {"CREATE_OR_MOVE_TAG": "1"},
                    "invalid create_or_move_tag",
                ),
                ({"RELEASE_TAG": ""}, "invalid release_tag"),
                ({"RELEASE_TAG": "-latest"}, "invalid release_tag"),
                ({"RELEASE_TAG": "invalid tag"}, "invalid release_tag"),
                ({"RELEASE_NAME": ""}, "invalid release_name"),
                ({"DIST_DIR": ""}, "invalid dist_dir"),
                ({"DIST_DIR": "-artifacts"}, "invalid dist_dir"),
                ({"DIST_DIR": str(root / "missing")}, "invalid dist_dir"),
                ({"DIST_DIR": str(empty_dist_dir)}, "invalid dist_dir"),
                ({"DIST_DIR": str(directory_dist_dir)}, "invalid release asset"),
                ({"DIST_DIR": str(fifo_dist_dir)}, "invalid release asset"),
                ({"DIST_DIR": str(symlink_dist_dir)}, "invalid release asset"),
                ({"DIST_DIR": str(symlinked_dist_dir)}, "invalid dist_dir"),
                ({"DIST_DIR": str(unreadable_dist_dir)}, "invalid release input"),
                ({"NOTES_FILE": str(root / "missing.md")}, "invalid notes_file"),
                (
                    {"NOTES_FILE": str(directory_dist_dir / "package.whl")},
                    "invalid notes_file",
                ),
                (
                    {"NOTES_FILE": str(fifo_dist_dir / "package.whl")},
                    "invalid notes_file",
                ),
                (
                    {"NOTES_FILE": str(symlink_dist_dir / "package.whl")},
                    "invalid notes_file",
                ),
                ({"NOTES_FILE": str(unreadable_asset)}, "invalid notes_file"),
                (
                    {"NOTES_FILE": str(symlinked_notes_parent / "notes.md")},
                    "invalid notes_file",
                ),
            )
            for overrides, expected_error in invalid_cases:
                with self.subTest(overrides=overrides):
                    github_output.write_text("", encoding="utf-8")
                    invalid = subprocess.run(
                        ("bash", "-c", script),
                        check=False,
                        env=os.environ | valid_env | overrides,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(2, invalid.returncode)
                    self.assertIn(expected_error, invalid.stderr)
                    self.assertEqual("", github_output.read_text(encoding="utf-8"))

            cleanup_step = action.split("    - name: Cleanup release transaction\n", 1)[
                1
            ]
            cleanup_script = dedent(cleanup_step.split("      run: |\n", 1)[1])
            cleaned = subprocess.run(
                ("bash", "-c", cleanup_script),
                check=False,
                env=os.environ
                | {
                    "RUNNER_TEMP": str(runner_temp),
                    "STAGE_ROOT": str(stage_root),
                    "TRANSACTION_ROOT": "",
                },
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, cleaned.returncode, cleaned.stderr)
            self.assertFalse(stage_root.exists())

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_secure_posix_paths_expand_only_trusted_root_aliases(self) -> None:
        helper_path = Path("scripts/release/secure_posix_paths.py").resolve()
        module_name = "secure_posix_paths_test"
        specification = importlib.util.spec_from_file_location(
            module_name,
            helper_path,
        )
        if specification is None or specification.loader is None:
            self.fail("secure POSIX path helper import failed")
        secure_posix_paths = importlib.util.module_from_spec(specification)
        previous_module = sys.modules.get(module_name)
        sys.modules[module_name] = secure_posix_paths
        try:
            specification.loader.exec_module(secure_posix_paths)
        finally:
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module
        system_alias = next(
            (
                candidate
                for candidate in map(Path, ("/var", "/tmp", "/bin", "/sbin", "/lib"))
                if candidate.is_symlink() and candidate.lstat().st_uid == 0
            ),
            None,
        )
        if system_alias is None:
            self.skipTest("root-owned system alias unavailable")
        target = Path(os.readlink(system_alias))
        expected = Path(system_alias.anchor, target)
        self.assertEqual(
            Path(os.path.abspath(expected)),
            secure_posix_paths.canonical_directory(system_alias),
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            target_directory = root / "target"
            target_directory.mkdir()
            untrusted_alias = root / "alias"
            untrusted_alias.symlink_to(target_directory, target_is_directory=True)
            with self.assertRaises(secure_posix_paths.SecurePathError):
                secure_posix_paths.canonical_directory(untrusted_alias)

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_release_snapshot_accepts_workspace_alias_not_internal_symlink(
        self,
    ) -> None:
        snapshot_script = Path("scripts/release/stage-release-inputs.py").resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            source_dir = workspace / "release"
            runner_temp = root / "runner-temp"
            source_dir.mkdir(parents=True)
            runner_temp.mkdir()
            payload = b"wheel"
            digest = hashlib.sha256(payload).hexdigest()
            (source_dir / "package.whl").write_bytes(payload)
            (source_dir / "SHA256SUMS.txt").write_text(
                f"{digest}  package.whl\n",
                encoding="utf-8",
            )
            alias_root = root.parent / f"{root.name}-lexical-alias"
            try:
                alias_root.symlink_to(root, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            try:
                alias_workspace = alias_root / "workspace"
                aliased = subprocess.run(
                    (
                        sys.executable,
                        str(snapshot_script),
                        "stage",
                        str(alias_workspace / "release"),
                        "",
                        str(runner_temp),
                    ),
                    check=False,
                    env=os.environ | {"GITHUB_WORKSPACE": str(alias_workspace)},
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, aliased.returncode, aliased.stderr)
                stage_root = Path(aliased.stdout.strip())
                self.assertEqual(
                    payload,
                    (stage_root / "assets" / "package.whl").read_bytes(),
                )
                subprocess.run(
                    (
                        sys.executable,
                        str(snapshot_script),
                        "cleanup",
                        str(stage_root),
                        str(runner_temp),
                    ),
                    check=True,
                    text=True,
                    capture_output=True,
                )

                linked_source = workspace / "linked-release"
                linked_source.symlink_to(source_dir, target_is_directory=True)
                rejected = subprocess.run(
                    (
                        sys.executable,
                        str(snapshot_script),
                        "stage",
                        str(linked_source),
                        "",
                        str(runner_temp),
                    ),
                    check=False,
                    env=os.environ | {"GITHUB_WORKSPACE": str(workspace)},
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(2, rejected.returncode)
                self.assertIn("symbolic links are not allowed", rejected.stderr)
                self.assertEqual([], list(runner_temp.iterdir()))
            finally:
                alias_root.unlink(missing_ok=True)

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_release_snapshot_rejects_inventory_tampering(self) -> None:
        snapshot_script = Path("scripts/release/stage-release-inputs.py").resolve()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            source_dir = workspace / "release"
            runner_temp = root / "runner-temp"
            source_dir.mkdir(parents=True)
            runner_temp.mkdir()
            payload = b"wheel"
            digest = hashlib.sha256(payload).hexdigest()
            (source_dir / "package.whl").write_bytes(payload)
            (source_dir / "SHA256SUMS.txt").write_text(
                f"{digest}  package.whl\n", encoding="utf-8"
            )
            notes_file = workspace / "notes.md"
            notes_file.write_text("release notes\n", encoding="utf-8")
            env = os.environ | {"GITHUB_WORKSPACE": str(workspace)}

            env_without_workspace = dict(os.environ)
            env_without_workspace.pop("GITHUB_WORKSPACE", None)
            missing_workspace = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "stage",
                    str(source_dir),
                    str(notes_file),
                    str(runner_temp),
                ),
                check=False,
                env=env_without_workspace,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, missing_workspace.returncode)
            self.assertIn("invalid GITHUB_WORKSPACE", missing_workspace.stderr)
            self.assertEqual([], list(runner_temp.iterdir()))

            symlink_manifest_source = workspace / "symlink-manifest"
            symlink_manifest_source.mkdir()
            (symlink_manifest_source / "package.whl").write_bytes(payload)
            manifest_target = workspace / "manifest-target.txt"
            manifest_target.write_text(f"{digest}  package.whl\n", encoding="utf-8")
            (symlink_manifest_source / "SHA256SUMS.txt").symlink_to(manifest_target)
            symlink_manifest = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "stage",
                    str(symlink_manifest_source),
                    "",
                    str(runner_temp),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, symlink_manifest.returncode)
            self.assertIn("missing regular SHA256SUMS.txt", symlink_manifest.stderr)
            self.assertEqual([], list(runner_temp.iterdir()))

            fifo_manifest_source = workspace / "fifo-manifest"
            fifo_manifest_source.mkdir()
            (fifo_manifest_source / "package.whl").write_bytes(payload)
            os.mkfifo(fifo_manifest_source / "SHA256SUMS.txt")
            fifo_manifest = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "stage",
                    str(fifo_manifest_source),
                    "",
                    str(runner_temp),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(2, fifo_manifest.returncode)
            self.assertIn("missing regular SHA256SUMS.txt", fifo_manifest.stderr)
            self.assertEqual([], list(runner_temp.iterdir()))

            staged = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "stage",
                    str(source_dir),
                    str(notes_file),
                    str(runner_temp),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, staged.returncode, staged.stderr)
            stage_root = Path(staged.stdout.strip())

            def verify_snapshot() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    (
                        sys.executable,
                        str(snapshot_script),
                        "verify",
                        str(stage_root),
                    ),
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )

            def assert_snapshot_rejected(message: str) -> None:
                rejected = verify_snapshot()
                self.assertEqual(2, rejected.returncode)
                self.assertIn(message, rejected.stderr)

            (source_dir / "package.whl").write_bytes(b"changed source")
            notes_file.write_text("changed source notes\n", encoding="utf-8")
            verified = verify_snapshot()
            self.assertEqual(0, verified.returncode, verified.stderr)
            staged_asset = stage_root / "assets" / "package.whl"
            staged_notes = stage_root / "release-notes.md"
            self.assertEqual(payload, staged_asset.read_bytes())
            self.assertEqual(
                "release notes\n", staged_notes.read_text(encoding="utf-8")
            )

            outside_source = root / "outside-release"
            outside_source.mkdir()
            (outside_source / "package.whl").write_bytes(payload)
            (outside_source / "SHA256SUMS.txt").write_text(
                f"{digest}  package.whl\n", encoding="utf-8"
            )
            outside = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "stage",
                    str(outside_source),
                    "",
                    str(runner_temp),
                ),
                check=False,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, outside.returncode)
            self.assertIn("escapes GITHUB_WORKSPACE", outside.stderr)

            assets_dir = stage_root / "assets"
            assets_dir.chmod(0o700)
            extra_asset = assets_dir / "extra.whl"
            extra_asset.write_bytes(b"extra")
            assets_dir.chmod(0o500)
            assert_snapshot_rejected("asset inventory")
            assets_dir.chmod(0o700)
            extra_asset.unlink()
            staged_asset.unlink()
            assets_dir.chmod(0o500)
            assert_snapshot_rejected("asset inventory")
            assets_dir.chmod(0o700)
            staged_asset.write_bytes(payload)
            staged_asset.chmod(0o400)
            assets_dir.chmod(0o500)

            staged_notes.chmod(0o600)
            staged_notes.write_text("tampered notes\n", encoding="utf-8")
            staged_notes.chmod(0o400)
            assert_snapshot_rejected("notes checksum mismatch")
            staged_notes.chmod(0o600)
            staged_notes.write_text("release notes\n", encoding="utf-8")
            staged_notes.chmod(0o400)

            metadata_path = stage_root / "snapshot.json"
            metadata_payload = metadata_path.read_bytes()
            metadata_path.chmod(0o600)
            metadata_path.write_text("{}\n", encoding="utf-8")
            metadata_path.chmod(0o400)
            assert_snapshot_rejected("metadata shape")
            metadata_path.chmod(0o600)
            metadata_path.write_bytes(metadata_payload)
            metadata_path.chmod(0o400)

            boolean_version = json.loads(metadata_payload)
            boolean_version["version"] = True
            metadata_path.chmod(0o600)
            metadata_path.write_text(json.dumps(boolean_version), encoding="utf-8")
            metadata_path.chmod(0o400)
            assert_snapshot_rejected("metadata version")
            metadata_path.chmod(0o600)
            metadata_path.write_bytes(metadata_payload)
            metadata_path.chmod(0o400)

            metadata_target = root / "snapshot-target.json"
            metadata_target.write_bytes(metadata_payload)
            metadata_path.unlink()
            metadata_path.symlink_to(metadata_target)
            assert_snapshot_rejected("missing snapshot.json")
            metadata_path.unlink()
            metadata_path.write_bytes(metadata_payload)
            metadata_path.chmod(0o400)

            metadata_path.unlink()
            os.mkfifo(metadata_path)
            fifo_metadata = verify_snapshot()
            self.assertEqual(2, fifo_metadata.returncode)
            self.assertIn("missing snapshot.json", fifo_metadata.stderr)
            metadata_path.unlink()
            metadata_path.write_bytes(metadata_payload)
            metadata_path.chmod(0o400)

            extra_root_file = stage_root / "extra"
            extra_root_file.write_bytes(b"extra")
            assert_snapshot_rejected("root inventory")
            extra_root_file.unlink()

            staged_asset.chmod(0o600)
            staged_asset.write_bytes(b"tampered")
            staged_asset.chmod(0o400)
            tampered = verify_snapshot()
            self.assertEqual(2, tampered.returncode)
            self.assertIn("checksum mismatch", tampered.stderr)
            cleanup_escape = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "cleanup",
                    str(stage_root),
                    str(root),
                ),
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(2, cleanup_escape.returncode)
            self.assertIn("cleanup boundary", cleanup_escape.stderr)
            self.assertTrue(stage_root.exists())
            cleaned = subprocess.run(
                (
                    sys.executable,
                    str(snapshot_script),
                    "cleanup",
                    str(stage_root),
                    str(runner_temp),
                ),
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, cleaned.returncode, cleaned.stderr)
            self.assertFalse(stage_root.exists())

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_release_snapshot_reports_partial_cleanup_failure(self) -> None:
        snapshot_script = Path("scripts/release/stage-release-inputs.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "stage_release_inputs_test", snapshot_script
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            source_dir = workspace / "release"
            runner_temp = root / "runner-temp"
            source_dir.mkdir(parents=True)
            runner_temp.mkdir()
            (source_dir / "package.whl").write_bytes(b"wheel")
            (source_dir / "SHA256SUMS.txt").write_text(
                f"{'0' * 64}  package.whl\n", encoding="utf-8"
            )
            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}),
                patch.object(
                    module,
                    "_remove_bound_tree",
                    side_effect=OSError("cleanup denied"),
                ),
                self.assertRaises(module.SnapshotError) as raised,
            ):
                module._stage(str(source_dir), "", str(runner_temp))
        self.assertIn("checksum mismatch", str(raised.exception))
        self.assertIn("partial cleanup failed: cleanup denied", str(raised.exception))

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_release_snapshot_cleans_setup_failure(self) -> None:
        snapshot_script = Path("scripts/release/stage-release-inputs.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "stage_release_setup_test", snapshot_script
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            source_dir = workspace / "release"
            runner_temp = root / "runner-temp"
            stage_root = runner_temp / "justdocs-release-setup"
            source_dir.mkdir(parents=True)
            runner_temp.mkdir()
            canonical_runner_temp = module._canonical_directory(runner_temp)
            canonical_stage_root = canonical_runner_temp / stage_root.name
            payload = b"wheel"
            digest = hashlib.sha256(payload).hexdigest()
            (source_dir / "package.whl").write_bytes(payload)
            (source_dir / "SHA256SUMS.txt").write_text(
                f"{digest}  package.whl\n", encoding="utf-8"
            )
            original_mkdir_at = module._mkdir_at

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}),
                patch.object(module.os, "O_NOFOLLOW", None),
                self.assertRaisesRegex(module.SnapshotError, "requires os.O_NOFOLLOW"),
            ):
                module._stage(str(source_dir), "", str(runner_temp))
            self.assertEqual([], list(runner_temp.iterdir()))

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}),
                patch.object(module.os, "O_NONBLOCK", None),
                self.assertRaisesRegex(module.SnapshotError, "requires os.O_NONBLOCK"),
            ):
                module._stage(str(source_dir), "", str(runner_temp))
            self.assertEqual([], list(runner_temp.iterdir()))

            def create_stage_root(*_args: object, **kwargs: object) -> str:
                self.assertEqual(canonical_runner_temp, kwargs["dir"])
                os.mkdir(stage_root, 0o700)
                return str(stage_root)

            def reject_assets_mkdir(
                directory_descriptor: int,
                name: str,
                mode: int,
            ) -> None:
                self.assertEqual(
                    canonical_stage_root.stat().st_ino,
                    os.fstat(directory_descriptor).st_ino,
                )
                if name == module.ASSETS_NAME:
                    raise OSError("assets mkdir denied")
                original_mkdir_at(directory_descriptor, name, mode)

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}),
                patch.object(
                    module.tempfile,
                    "mkdtemp",
                    side_effect=create_stage_root,
                ),
                patch.object(module, "_mkdir_at", new=reject_assets_mkdir),
                self.assertRaisesRegex(OSError, "assets mkdir denied"),
            ):
                module._stage(str(source_dir), "", str(runner_temp))
            self.assertFalse(stage_root.exists())
            self.assertFalse(canonical_stage_root.exists())

            outside = root / "outside"
            escaped_root = outside / "justdocs-release-escape"
            outside.mkdir()

            def create_escaped_root(*_args: object, **kwargs: object) -> str:
                self.assertEqual(canonical_runner_temp, kwargs["dir"])
                escaped_root.mkdir()
                return str(escaped_root)

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}),
                patch.object(
                    module.tempfile,
                    "mkdtemp",
                    side_effect=create_escaped_root,
                ),
                self.assertRaisesRegex(
                    module.SnapshotError,
                    "invalid release snapshot creation boundary",
                ),
            ):
                module._stage(str(source_dir), "", str(runner_temp))
            self.assertTrue(escaped_root.is_dir())
            escaped_root.rmdir()

            for replacement_kind in ("symlink", "directory"):
                with self.subTest(replacement_kind=replacement_kind):
                    displaced_root = runner_temp / f"displaced-{replacement_kind}"

                    def substitute_before_assets(
                        directory_descriptor: int,
                        name: str,
                        mode: int,
                    ) -> None:
                        self.assertEqual(module.ASSETS_NAME, name)
                        self.assertEqual(
                            canonical_stage_root.stat().st_ino,
                            os.fstat(directory_descriptor).st_ino,
                        )
                        stage_root.rename(displaced_root)
                        if replacement_kind == "symlink":
                            stage_root.symlink_to(outside, target_is_directory=True)
                        else:
                            stage_root.mkdir()
                        original_mkdir_at(directory_descriptor, name, mode)

                    with (
                        patch.dict(
                            os.environ,
                            {"GITHUB_WORKSPACE": str(workspace)},
                        ),
                        patch.object(
                            module.tempfile,
                            "mkdtemp",
                            side_effect=create_stage_root,
                        ),
                        patch.object(
                            module,
                            "_mkdir_at",
                            new=substitute_before_assets,
                        ),
                        self.assertRaisesRegex(
                            module.SnapshotError,
                            "root changed during staging",
                        ),
                    ):
                        module._stage(str(source_dir), "", str(runner_temp))
                    self.assertFalse((outside / module.ASSETS_NAME).exists())
                    self.assertEqual([], list(displaced_root.iterdir()))
                    if replacement_kind == "symlink":
                        self.assertTrue(stage_root.is_symlink())
                        stage_root.unlink()
                    else:
                        self.assertTrue(stage_root.is_dir())
                        self.assertEqual([], list(stage_root.iterdir()))
                        stage_root.rmdir()
                    displaced_root.rmdir()

    @unittest.skipIf(os.name == "nt", "POSIX release snapshot path")
    def test_release_snapshot_cleanup_rejects_nested_substitution(self) -> None:
        snapshot_script = Path("scripts/release/stage-release-inputs.py").resolve()
        specification = importlib.util.spec_from_file_location(
            "stage_release_nested_cleanup_test",
            snapshot_script,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_root = root / "justdocs-release-nested"
            child = snapshot_root / "child"
            displaced_child = snapshot_root / "displaced-child"
            child.mkdir(parents=True)
            (child / "payload").write_bytes(b"payload")
            original_verify = module._verify_directory_entry
            substituted = False

            def substitute_before_identity_check(
                parent_descriptor: int,
                name: str,
                descriptor: int,
                error_message: str,
            ) -> None:
                nonlocal substituted
                if name == child.name and not substituted:
                    substituted = True
                    child.rename(displaced_child)
                    child.mkdir()
                original_verify(
                    parent_descriptor,
                    name,
                    descriptor,
                    error_message,
                )

            canonical_snapshot_root = module._canonical_directory(snapshot_root)
            with module._open_absolute_directory(
                canonical_snapshot_root
            ) as root_descriptor:
                with (
                    patch.object(
                        module,
                        "_verify_directory_entry",
                        new=substitute_before_identity_check,
                    ),
                    self.assertRaisesRegex(
                        module.SnapshotError,
                        "directory changed during cleanup",
                    ),
                ):
                    module._remove_directory_contents(root_descriptor)
            self.assertTrue(substituted)
            self.assertTrue(child.is_dir())
            self.assertEqual([], list(child.iterdir()))
            self.assertTrue(displaced_child.is_dir())
            self.assertEqual([], list(displaced_child.iterdir()))
            child.rmdir()
            displaced_child.rmdir()
            snapshot_root.rmdir()

    def test_bootstrap_installers_expose_global_install_contract(self) -> None:
        shell = Path("install.sh").read_text(encoding="utf-8")
        powershell = Path("install.ps1").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        project_setup = Path("examples/basic/docs/guides/project-setup.md").read_text(
            encoding="utf-8"
        )
        reference = Path("examples/basic/docs/reference.md").read_text(encoding="utf-8")
        docs = "\n".join((readme, project_setup, reference))
        for term in (
            "set -eu",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_TIMEOUT",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_MODIFY_PATH",
            "justdocs-managed-v1",
            "-m pip install --upgrade",
            "archive/${ref}.tar.gz",
            "api.github.com/repos/{repository}/releases/latest",
            "browser_download_url",
            "# >>> justdocs PATH >>>",
            '"$command_path" version',
        ):
            with self.subTest(shell_term=term):
                self.assertIn(term, shell)
        for term in (
            "$ErrorActionPreference = 'Stop'",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_VERSION",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_TIMEOUT",
            "JUSTDOCS_INSTALL_SPEC",
            "JUSTDOCS_INSTALL_DRY_RUN",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_MODIFY_PATH",
            "-m pip install --upgrade",
            "archive/$Ref.tar.gz",
            "api.github.com/repos/{repository}/releases/latest",
            "browser_download_url",
            "SetEnvironmentVariable('Path'",
            "& $CommandPath version",
            "$script:PythonCommand = @(Resolve-JustdocsPython)",
        ):
            with self.subTest(powershell_term=term):
                self.assertIn(term, powershell)
        for term in (
            "curl -fsSL https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.sh | sh",
            "irm https://github.com/FanaticPythoner/justdocs/releases/latest/download/install.ps1 | iex",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
        ):
            with self.subTest(docs_term=term):
                self.assertIn(term, docs)

        syntax = subprocess.run(
            ("sh", "-n", "install.sh"), check=False, text=True, capture_output=True
        )
        self.assertEqual("", syntax.stderr)
        self.assertEqual(0, syntax.returncode)
        if os.name != "nt":
            self.assertTrue(os.access("install.sh", os.X_OK))

        if os.name == "nt":
            with TemporaryDirectory() as directory:
                root = Path(directory) / "justdocs"
                windows_env = os.environ | {
                    "JUSTDOCS_INSTALL_DRY_RUN": "1",
                    "JUSTDOCS_PYTHON": sys.executable,
                    "JUSTDOCS_INSTALL_ROOT": str(root),
                    "JUSTDOCS_INSTALL_REF": "v0.1.0",
                }
                windows_run = subprocess.run(
                    (
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        "install.ps1",
                    ),
                    check=False,
                    env=windows_env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual("", windows_run.stderr)
                self.assertEqual(0, windows_run.returncode)
                self.assertTrue(
                    windows_run.stdout.startswith(f"{sys.executable} -m venv "),
                    windows_run.stdout,
                )
                self.assertIn("archive/v0.1.0.tar.gz", windows_run.stdout)
            return

        env = os.environ.copy()
        install_root = Path("/tmp/justdocs-test-root").resolve()
        env.update(
            {
                "JUSTDOCS_INSTALL_DRY_RUN": "1",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_INSTALL_ROOT": "/tmp/justdocs-test-root",
                "JUSTDOCS_SHELL_PROFILE": "/tmp/justdocs-test-profile",
                "JUSTDOCS_INSTALL_REF": "v0.1.0",
            },
        )
        dry_run = subprocess.run(
            ("sh", "install.sh"), check=False, env=env, text=True, capture_output=True
        )
        self.assertEqual("", dry_run.stderr)
        self.assertEqual(0, dry_run.returncode)
        self.assertIn(
            f"{sys.executable} -m venv {install_root / 'venv'}", dry_run.stdout
        )
        self.assertIn(
            f"{install_root / 'venv' / 'bin' / 'python'} -m pip install --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/v0.1.0.tar.gz",
            dry_run.stdout,
        )
        self.assertIn(f"link {install_root / 'bin' / 'justdocs'}", dry_run.stdout)

        with TemporaryDirectory() as resolver_directory:
            payload = json.dumps(github_release_payload("0.1.0"))
            Path(resolver_directory, "sitecustomize.py").write_text(
                "import io\n"
                "import urllib.request\n"
                f"PAYLOAD = {payload!r}.encode('utf-8')\n"
                "class Response(io.BytesIO):\n"
                "    def __enter__(self): return self\n"
                "    def __exit__(self, exc_type, exc_value, traceback): return False\n"
                "urllib.request.urlopen = lambda request, timeout: Response(PAYLOAD)\n",
                encoding="utf-8",
            )
            resolver_env = env | {"PYTHONPATH": resolver_directory}
            resolver_env.pop("JUSTDOCS_INSTALL_REF")
            latest_run = subprocess.run(
                ("sh", "install.sh"),
                check=False,
                env=resolver_env,
                text=True,
                capture_output=True,
            )
        self.assertEqual(0, latest_run.returncode, latest_run.stderr)
        self.assertIn(
            "releases/download/v0.1.0/justdocs-0.1.0-py3-none-any.whl",
            latest_run.stdout,
        )

        invalid_boolean = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=env | {"JUSTDOCS_MODIFY_PATH": "invalid"},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_boolean.returncode)
        self.assertIn("invalid JUSTDOCS_MODIFY_PATH", invalid_boolean.stderr)

        invalid_spec = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=env | {"JUSTDOCS_INSTALL_SPEC": "--target=/tmp/justdocs justdocs"},
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_spec.returncode)
        self.assertIn("pip option rejected", invalid_spec.stderr)

        latest_env = env | {"JUSTDOCS_INSTALL_TIMEOUT": "invalid"}
        latest_env.pop("JUSTDOCS_INSTALL_REF")
        invalid_timeout = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=latest_env,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, invalid_timeout.returncode)
        self.assertIn("invalid JUSTDOCS_INSTALL_TIMEOUT", invalid_timeout.stderr)

        pypi_env = env | {"JUSTDOCS_INSTALL_SOURCE": "pypi"}
        pypi_run = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=pypi_env,
            text=True,
            capture_output=True,
        )
        self.assertEqual("", pypi_run.stderr)
        self.assertEqual(0, pypi_run.returncode)
        self.assertIn(
            f"{install_root / 'venv' / 'bin' / 'python'} "
            "-m pip install --upgrade justdocs",
            pypi_run.stdout,
        )

        github_env = env | {
            "JUSTDOCS_INSTALL_SOURCE": "github",
            "JUSTDOCS_INSTALL_REF": "v0.1.0",
        }
        github_run = subprocess.run(
            ("sh", "install.sh"),
            check=False,
            env=github_env,
            text=True,
            capture_output=True,
        )
        self.assertEqual("", github_run.stderr)
        self.assertEqual(0, github_run.returncode)
        self.assertIn(
            f"{install_root / 'venv' / 'bin' / 'python'} -m pip install --upgrade "
            "https://github.com/FanaticPythoner/justdocs/archive/v0.1.0.tar.gz",
            github_run.stdout,
        )

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap safety path")
    def test_bootstrap_uninstall_rejects_unsafe_and_unmanaged_roots(self) -> None:
        with TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            profile = home / ".bashrc"
            unmanaged = Path(directory) / "unmanaged"
            home.mkdir()
            unmanaged.mkdir()
            marker = unmanaged / "preserved"
            marker.write_text("x", encoding="utf-8")
            tampered = Path(directory) / "tampered"
            (tampered / "bin").mkdir(parents=True)
            (tampered / ".justdocs-managed").write_text(
                "justdocs-managed-v1\n", encoding="utf-8"
            )
            tampered_command = tampered / "bin" / "justdocs"
            tampered_command.write_text("unowned\n", encoding="utf-8")
            marker_target = Path(directory) / "marker-target"
            marker_target.write_text("justdocs-managed-v1\n", encoding="utf-8")
            linked_marker = Path(directory) / "linked-marker"
            linked_marker.mkdir()
            (linked_marker / ".justdocs-managed").symlink_to(marker_target)
            base_env = os.environ | {
                "HOME": str(home),
                "SHELL": "/bin/bash",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_SHELL_PROFILE": str(profile),
                "JUSTDOCS_INSTALL_ACTION": "uninstall",
            }
            for root, expected in (
                (home, "unsafe JUSTDOCS_INSTALL_ROOT"),
                (unmanaged, "refusing to remove unmanaged install root"),
                (tampered, "refusing to modify unowned command"),
                (linked_marker, "invalid install ownership marker symlink"),
            ):
                with self.subTest(root=root):
                    completed = subprocess.run(
                        ("sh", "install.sh"),
                        env=base_env | {"JUSTDOCS_INSTALL_ROOT": str(root)},
                        check=False,
                        text=True,
                        capture_output=True,
                    )
                    self.assertNotEqual(0, completed.returncode)
                    self.assertIn(expected, completed.stderr)
            self.assertEqual("x", marker.read_text(encoding="utf-8"))
            self.assertEqual("unowned\n", tampered_command.read_text(encoding="utf-8"))
            self.assertEqual(
                "justdocs-managed-v1\n", marker_target.read_text(encoding="utf-8")
            )

    @unittest.skipIf(os.name == "nt", "POSIX bootstrap lock path")
    def test_bootstrap_recovers_stale_lock_and_rejects_live_lock(self) -> None:
        with TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            root = Path(directory) / "managed"
            lock = Path(str(root) + ".install-lock")
            home.mkdir()
            lock.mkdir()
            (lock / "pid").write_text("999999999\n", encoding="utf-8")
            environment = os.environ | {
                "HOME": str(home),
                "SHELL": "/bin/bash",
                "JUSTDOCS_PYTHON": sys.executable,
                "JUSTDOCS_INSTALL_ROOT": str(root),
                "JUSTDOCS_SHELL_PROFILE": str(home / ".bashrc"),
                "JUSTDOCS_INSTALL_ACTION": "uninstall",
            }
            recovered = subprocess.run(
                ("sh", "install.sh"),
                env=environment,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, recovered.returncode, recovered.stderr)
            self.assertFalse(lock.exists())

            lock.mkdir()
            (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            held = subprocess.run(
                ("sh", "install.sh"),
                env=environment,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(0, held.returncode)
            self.assertIn("installer lock is held", held.stderr)

    def test_global_cli_install_delegates_to_platform_bootstrap(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "justdocs"\n', encoding="utf-8"
            )
            (root / ("install.ps1" if os.name == "nt" else "install.sh")).write_text(
                "", encoding="utf-8"
            )
            environment = {"JUSTDOCS_INSTALL_ROOT": str(root / "managed")}
            resolved = (
                Path(environment["JUSTDOCS_INSTALL_ROOT"]).resolve()
                / "bin"
                / ("justdocs.exe" if os.name == "nt" else "justdocs")
            )
            with (
                patch.object(
                    global_cli, "bootstrap_environment", return_value=environment
                ) as bootstrap_environment,
                patch.object(global_cli, "run_bootstrap") as run_bootstrap,
            ):
                self.assertEqual(resolved, global_cli.install(root))
        bootstrap_environment.assert_called_once_with("install", root.resolve())
        run_bootstrap.assert_called_once_with(root.resolve(), environment)

    def test_global_cli_uninstall_delegates_to_platform_bootstrap(self) -> None:
        root = Path.cwd().resolve()
        environment = {"JUSTDOCS_INSTALL_ACTION": "uninstall"}
        with (
            patch.object(global_cli, "bootstrap_environment", return_value=environment),
            patch.object(
                global_cli,
                "run_bootstrap",
            ) as run_bootstrap,
        ):
            global_cli.uninstall(root)
        run_bootstrap.assert_called_once_with(root, environment)

    def test_global_cli_install_requires_project_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(GlobalCliError):
                global_cli.install(Path(directory))

    def test_project_recipe_install_runs_venv_and_locked_pip(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            source = Path(directory) / "source"
            root.mkdir()
            source.mkdir()
            (source / "pyproject.toml").write_text(
                '[project]\nname = "justdocs"\n', encoding="utf-8"
            )
            config = ProjectRecipeConfig(
                root=root,
                package="../source",
                extra_packages="pymdown-extensions==10.12",
                python="python",
            )
            venv_python = str(config.venv_python)
            with (
                patch.object(
                    project_recipes, "install_lock", return_value=nullcontext()
                ),
                patch.object(project_recipes, "run_command") as run_command,
            ):
                project_recipes.install(config)
        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(
            ("python", "-m", "venv", str(config.resolved_venv)), commands[0]
        )
        self.assertEqual(
            (
                venv_python,
                "-m",
                "pip",
                "install",
                "../source",
                "pymdown-extensions==10.12",
            ),
            commands[1],
        )

    def test_project_recipe_locks_all_local_sources_in_sorted_order(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            source_a = root / "source-a"
            source_b = root / "source-b"
            for path in (root, source_a, source_b):
                path.mkdir()
            for path in (source_a, source_b):
                (path / "pyproject.toml").write_text(
                    '[project]\nname = "local"\n', encoding="utf-8"
                )
            config = ProjectRecipeConfig(
                root=root,
                package="source-b",
                extra_packages="source-a",
                python="python",
            )
            entered: list[Path] = []

            def record_lock(path: Path):
                entered.append(path)
                return nullcontext()

            with (
                patch.object(project_recipes, "install_lock", side_effect=record_lock),
                patch.object(
                    project_recipes,
                    "run_command",
                ),
            ):
                project_recipes.install(config)
        self.assertEqual(
            [config.resolved_venv, source_a.resolve(), source_b.resolve()], entered
        )

    def test_project_recipe_check_runs_strict_mkdocs_build(self) -> None:
        config = ProjectRecipeConfig(root=Path("."), mkdocs_config="docs.yml")
        with (
            patch.object(project_recipes, "install") as install,
            patch.object(project_recipes, "run_command") as run_command,
        ):
            project_recipes.check(config)
        install.assert_called_once_with(config)
        command = run_command.call_args.args[0]
        self.assertEqual(
            (
                str(config.venv_python),
                "-m",
                "mkdocs",
                "build",
                "-f",
                "docs.yml",
                "--strict",
                "--clean",
            ),
            command,
        )

    def test_project_recipe_clean_removes_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("site", ".cache", ".mkdocs_cache"):
                path = root / relative
                path.mkdir()
                (path / "file").write_text("x", encoding="utf-8")
            project_recipes.clean(ProjectRecipeConfig(root=root))
            for relative in ("site", ".cache", ".mkdocs_cache"):
                self.assertFalse((root / relative).exists())

    @unittest.skipIf(
        os.name == "nt", "Windows symlink privilege is environment-dependent"
    )
    def test_project_recipe_clean_unlinks_output_symlink_without_traversal(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            marker = outside / "preserved"
            marker.write_text("x", encoding="utf-8")
            (root / "site").symlink_to(outside, target_is_directory=True)
            project_recipes.clean(ProjectRecipeConfig(root=root))
            self.assertFalse((root / "site").exists())
            self.assertEqual("x", marker.read_text(encoding="utf-8"))

    def test_project_recipe_rejects_destructive_venv_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            marker = outside / "preserved"
            marker.write_text("x", encoding="utf-8")
            for venv in (Path("."), outside, Path("../outside")):
                with self.subTest(venv=venv), self.assertRaises(ProjectRecipeError):
                    project_recipes.dist_clean(
                        ProjectRecipeConfig(root=root, venv=venv)
                    )
            self.assertEqual("x", marker.read_text(encoding="utf-8"))

    def test_project_recipe_free_port_rejects_invalid_port(self) -> None:
        with self.assertRaises(ProjectRecipeError):
            project_recipes.free_port(ProjectRecipeConfig(port="70000"))

    def test_project_recipe_rejects_malformed_listener_process_ids(self) -> None:
        with self.assertRaises(ProjectRecipeError):
            project_recipes._parse_pid_lines("1234 invalid")

    def test_linker_rejects_nonpositive_limits(self) -> None:
        valid = {
            "min_phrase_chars": 4,
            "max_links_per_page": 512,
            "max_links_per_target": 2,
        }
        for name in valid:
            with self.subTest(name=name), self.assertRaises(JustdocsLinkerError):
                _validate_linker_limits(valid | {name: 0})

    def test_theme_extends_mkdocs(self) -> None:
        config = (theme_dir() / "mkdocs_theme.yml").read_text(encoding="utf-8")
        self.assertIn("extends: mkdocs", config)

    def test_base_template_references_bundled_assets(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("window.JUSTDOCS", template)
        self.assertIn("rightDrawer", template)
        self.assertIn("contentWidth", template)
        self.assertIn("--font-text", template)
        self.assertIn("--radius-control", template)
        self.assertIn("justdocs_palette_light.link", template)
        self.assertIn("justdocs_palette_dark.link", template)
        self.assertIn("features: {", template)
        self.assertIn('id="hljs-light"', template)
        self.assertIn('id="hljs-dark"', template)
        for asset in REQUIRED_THEME_FILES:
            if not asset.startswith("assets/") or asset.endswith(".txt"):
                continue
            self.assertIn(asset, template)

    def test_base_template_exposes_sidebar_controls(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn('data-sidebar-toggle="left"', template)
        self.assertIn('data-sidebar-toggle="right"', template)
        self.assertIn('data-sidebar-resizer="left"', template)
        self.assertIn('data-sidebar-resizer="right"', template)
        self.assertIn('data-sidebar-restore="left"', template)
        self.assertIn('data-sidebar-restore="right"', template)
        self.assertIn('data-sidebar-scrim="right"', template)
        self.assertIn('role="separator"', template)

    def test_base_template_exposes_preferences(self) -> None:
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("justdocs-preferences-panel", template)
        self.assertIn("justdocs_preferences_enabled", template)
        self.assertIn('data-preference-choice="density"', template)
        self.assertIn('data-preference-choice="contentWidth"', template)
        self.assertIn('data-preference-choice="motion"', template)

    def test_main_template_extends_base(self) -> None:
        template = (theme_dir() / "main.html").read_text(encoding="utf-8")
        self.assertEqual('{% extends "base.html" %}', template.strip())

    def test_copy_button_plugin_exports_browser_global(self) -> None:
        plugin = (theme_dir() / "assets/js/highlightjs-copy.min.js").read_text(
            encoding="utf-8",
        )
        self.assertIn("window.CopyButtonPlugin = CopyButtonPlugin;", plugin)

    def test_theme_script_preserves_left_navigation_scroll(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("initializeNavigationScrollState", script)
        self.assertIn("justdocs-nav-scroll", script)
        self.assertIn("sessionStorage.setItem", script)
        self.assertIn("sessionStorage.getItem", script)

    def test_theme_script_resizes_and_collapses_sidebars(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("initializeSidebars", script)
        self.assertIn("justdocs-sidebar", script)
        self.assertIn("collapseMargin", script)
        self.assertIn("applyPointerSidebarWidth", script)
        self.assertIn("setViewportState", script)
        self.assertIn("syncTopbarHeight", script)
        self.assertIn("syncSidebarVisibility", script)
        self.assertIn(
            "const setSidebarCollapsed = (side, collapsed, persist = true)", script
        )
        self.assertIn('nextViewport === "drawer"', script)
        self.assertIn("initializePreferences", script)
        self.assertIn("setPointerCapture", script)
        self.assertIn("ArrowRight", script)
        self.assertIn("aria-valuenow", script)
        self.assertIn("aria-hidden", script)

    def test_theme_script_uses_configured_features(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        self.assertIn("FEATURES", script)
        self.assertIn("PREFERENCES_ENABLED", script)
        self.assertIn("configuredInteger", script)
        self.assertIn("FEATURES.search", script)
        self.assertIn("FEATURES.mermaid", script)
        self.assertIn("FEATURES.codeCopy", script)
        self.assertIn("copy button asset missing", script)

    def test_theme_script_renders_mermaid_blocks(self) -> None:
        script = (theme_dir() / "assets/js/theme.js").read_text(encoding="utf-8")
        template = (theme_dir() / "base.html").read_text(encoding="utf-8")
        self.assertIn("initializeMermaid", script)
        self.assertIn("renderMermaidBlocks", script)
        self.assertIn("window.mermaid.run", script)
        self.assertIn("assets/js/mermaid.min.js", template)

    def test_theme_css_marks_linked_code_as_links(self) -> None:
        css = (theme_dir() / "assets/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("main a[href]:not(.headerlink)", css)
        self.assertIn("text-decoration-thickness", css)
        self.assertIn("main a[href] > code", css)
        self.assertIn("border: 1px solid color-mix(in srgb, var(--link)", css)

    def test_theme_css_defines_responsive_sidebar_layout(self) -> None:
        css = (theme_dir() / "assets/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("--left-sidebar-width", css)
        self.assertIn("--right-sidebar-width", css)
        self.assertIn("--content-max-width", css)
        self.assertIn("--font-text", css)
        self.assertIn("--radius-control", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("font-family: var(--font-text)", css)
        self.assertIn("font-family: var(--font-mono)", css)
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn(".sidebar-resizer-left", css)
        self.assertIn(".sidebar-restore-left", css)
        self.assertIn(".sidebar-scrim", css)
        self.assertIn(".preferences-panel", css)
        self.assertIn('html[data-justdocs-viewport="mobile"]', css)
        self.assertIn('html[data-left-sidebar="collapsed"] nav.left', css)
        self.assertIn('html[data-left-sidebar="collapsed"] .sidebar-restore-left', css)

    def test_example_documents_customization_surface(self) -> None:
        config = Path("examples/basic/mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("nav:", config)
        self.assertIn("concepts/theme-configuration.md", config)
        self.assertIn("guides/project-setup.md", config)
        self.assertIn("guides/advanced/smart-links.md", config)
        self.assertIn("palette:", config)
        self.assertIn("typography:", config)
        self.assertIn("shape:", config)
        self.assertIn("features:", config)
        self.assertIn("content_width: standard", config)

    def test_docs_cover_current_contracts(self) -> None:
        root = Path("examples/basic/docs")
        docs = {
            "index": root / "index.md",
            "theme": root / "concepts/theme-configuration.md",
            "setup": root / "guides/project-setup.md",
            "links": root / "guides/advanced/smart-links.md",
            "reference": root / "reference.md",
        }
        for path in docs.values():
            self.assertTrue(path.is_file(), path)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in docs.values())
        readme = Path("README.md").read_text(encoding="utf-8")
        required_terms = (
            "justdocs-linker",
            "min_phrase_chars",
            "max_links_per_page",
            "max_links_per_target",
            "justdocs theme-dir",
            "justdocs projects init",
            "justdocs projects check",
            "justdocs version",
            "justdocs check-update",
            "justdocs update",
            "just global-install",
            "just dist",
            "just next-release",
            "JUSTDOCS_GLOBAL_PYTHON",
            "GlobalCliError",
            "ProjectRecipeError",
            "UpdateCheckError",
            "UpdateSourceEmpty",
            "UpdateInstallError",
            "install.sh",
            "install.ps1",
            "curl -fsSL",
            "JUSTDOCS_INSTALL_SOURCE",
            "JUSTDOCS_INSTALL_ACTION",
            "JUSTDOCS_INSTALL_ROOT",
            "JUSTDOCS_INSTALL_REF",
            "JUSTDOCS_INSTALL_SPEC",
            "isolated global command environment",
            ".github/actions/build-dist/action.yml",
            ".github/actions/release-assets/action.yml",
            ".github/workflows/pr-python-dist-comment.yml",
            "pypa/gh-action-pypi-publish",
            "PYPI_API_TOKEN",
            "PyPI trusted publisher",
            "CHANGELOG.md",
            "SHA256SUMS.txt",
            "3.14t",
            "packaging>=24",
            "ThemeAssetError",
            "TemplateAssetError",
            "ProjectJustfileExistsError",
            "ProjectJustfileInvalidPackageError",
            "ProjectJustfileWriteError",
            "search index fetch failed",
            "copy button asset missing",
            "assets/js/mermaid.LICENSE.txt",
            "justdocs-sidebar-left-state",
            "O(p * t * s)",
        )
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, readme)
                self.assertIn(term, combined)
        stale_terms = (
            "Service Discovery",
            "Deployment Guide",
            "Traffic Policy",
            "justdocs project ",
            "justdocs init ",
            "justdocs version --check",
            "just install-global",
            "just uninstall-global",
        )
        for term in stale_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, combined)

    def test_relative_url_uses_current_page_directory(self) -> None:
        self.assertEqual(
            "../concepts/service-discovery.md",
            _relative_url(
                "guides/deployment-guide.md", "concepts/service-discovery.md"
            ),
        )
        self.assertEqual(
            "guides/deployment-guide.md#release-flow",
            _relative_url("index.md", "guides/deployment-guide.md#release-flow"),
        )

    def test_heading_reference_ids_resolve_pages_and_steps(self) -> None:
        targets = tuple(
            _candidate_targets(
                "# [T1] Foundation\n\n## [J1] Verify inputs\n",
                "team/foundation.md",
            )
        )
        by_phrase = {target.phrase: target.url for target in targets}
        self.assertEqual("team/foundation.md", by_phrase["T1"])
        self.assertEqual(
            "team/foundation.md#j1-verify-inputs", by_phrase["J1"]
        )
        self.assertEqual("team/foundation.md", by_phrase["Foundation"])

    def test_heading_references_exclude_fenced_examples(self) -> None:
        targets = tuple(
            _candidate_targets(
                "```markdown\n# [T9] Example\n```\n\n# [T1] Foundation\n",
                "team/foundation.md",
            )
        )
        phrases = {target.phrase for target in targets}
        self.assertIn("T1", phrases)
        self.assertNotIn("T9", phrases)
        self.assertNotIn("[T9] Example", phrases)

    def test_short_reference_ids_preserve_phrase_threshold(self) -> None:
        targets = _dedupe_targets(
            (
                LinkTarget("F1", "forge/setup.md", "forge/setup.md"),
                LinkTarget("FD", "limits.md", "limits.md"),
            ),
            4,
        )
        self.assertEqual(["F1"], [target.phrase for target in targets])

    def test_duplicate_reference_ids_reject_conflicting_targets(self) -> None:
        with self.assertRaisesRegex(JustdocsLinkerError, "duplicate reference id"):
            _dedupe_targets(
                (
                    LinkTarget("F1", "forge/setup.md", "forge/setup.md"),
                    LinkTarget("f1", "forge/other.md", "forge/other.md"),
                ),
                4,
            )

    def test_reference_links_cover_dependencies_steps_and_inline_code(self) -> None:
        targets = _dedupe_targets(
            (
                LinkTarget("F1", "forge/setup.md", "forge/setup.md"),
                LinkTarget("F11", "forge/handoff.md", "forge/handoff.md"),
                LinkTarget("J1", "joint/run.md#j1-verify-inputs", "joint/run.md"),
            ),
            4,
        )
        markdown = (
            "Requires F1, F11, `J1`, F111.\n\n"
            "[F1](existing.md)\n\n```text\nF1 J1\n```\n"
        )
        linked = _smart_link_markdown(
            markdown, "terraform/workflow.md", "terraform/workflow.md", targets, 8
        )
        self.assertIn("Requires [F1](../forge/setup.md)", linked)
        self.assertIn("[F11](../forge/handoff.md)", linked)
        self.assertIn("[`J1`](../joint/run.md#j1-verify-inputs)", linked)
        self.assertIn("F111", linked)
        self.assertIn("[F1](existing.md)", linked)
        self.assertIn("```text\nF1 J1\n```", linked)

    def test_reference_links_repeat_without_consuming_phrase_limit(self) -> None:
        targets = (
            LinkTarget("F1", "forge/setup.md", "forge/setup.md"),
            LinkTarget("Foundation", "foundation.md", "foundation.md"),
        )
        linked = _smart_link_markdown(
            "F1 F1 F1 `F1` Foundation Foundation",
            "index.md",
            "index.md",
            targets,
            8,
            max_links_per_target=1,
        )
        self.assertEqual(4, linked.count("forge/setup.md"))
        self.assertEqual(1, linked.count("](foundation.md)"))

    def test_reference_links_obey_page_limit(self) -> None:
        linked = _smart_link_markdown(
            "F1 F1 F1 `F1`",
            "index.md",
            "index.md",
            (LinkTarget("F1", "forge/setup.md", "forge/setup.md"),),
            2,
            max_links_per_target=1,
        )
        self.assertEqual(2, linked.count("forge/setup.md"))

    def test_reference_links_reach_sections_on_current_page(self) -> None:
        targets = (
            LinkTarget("J1", "joint/run.md#j1-verify-inputs", "joint/run.md"),
            LinkTarget("J2", "joint/run.md#j2-apply-foundation", "joint/run.md"),
        )
        linked = _smart_link_markdown(
            "J2 requires J1 and `J1`.",
            "joint/run.md",
            "joint/run.md",
            targets,
            8,
        )
        self.assertIn("[J2](#j2-apply-foundation)", linked)
        self.assertIn("[J1](#j1-verify-inputs)", linked)
        self.assertIn("[`J1`](#j1-verify-inputs)", linked)

    def test_reference_links_skip_current_page_without_fragment(self) -> None:
        text = "F1 uses `F1`."
        linked = _smart_link_markdown(
            text,
            "forge/setup.md",
            "forge/setup.md",
            (LinkTarget("F1", "forge/setup.md", "forge/setup.md"),),
            8,
        )
        self.assertEqual(text, linked)

    def test_smart_link_markdown_links_tables_and_prose(self) -> None:
        markdown = (
            "# Home\n\n"
            "| Topic | Existing |\n"
            "| --- | --- |\n"
            "| Theme Configuration | [Smart Links](custom.md) |\n\n"
            "Project Setup consumes `Theme Configuration`.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    Theme Configuration --> Project Setup\n"
            "```\n"
            "\n"
            "Theme Configuration remains plain text after the diagram.\n"
        )
        targets = (
            LinkTarget(
                "Theme Configuration",
                "concepts/theme-configuration.md",
                "concepts/theme-configuration.md",
            ),
            LinkTarget(
                "Project Setup", "guides/project-setup.md", "guides/project-setup.md"
            ),
            LinkTarget(
                "Smart Links",
                "guides/advanced/smart-links.md",
                "guides/advanced/smart-links.md",
            ),
        )
        linked = _smart_link_markdown(markdown, "index.md", "index.md", targets, 8)
        self.assertIn(
            "| [Theme Configuration](concepts/theme-configuration.md) |", linked
        )
        self.assertIn("[Project Setup](guides/project-setup.md) consumes", linked)
        self.assertIn(
            "[Theme Configuration](concepts/theme-configuration.md) remains", linked
        )
        self.assertIn("`Theme Configuration`", linked)
        self.assertIn("[Smart Links](custom.md)", linked)
        self.assertIn("Theme Configuration --> Project Setup", linked)

    def test_smart_link_markdown_links_action_ids_inside_inline_code(self) -> None:
        markdown = (
            "# P2-0001 - Define Mermaid source contract document\n\n"
            "## Preconditions\n\n"
            "- `P1-0008` complete\n\n"
            "## Dependencies\n\n"
            "- `P2-0002`\n"
            "- `P8-0020`\n\n"
            "```yaml\n"
            "action: P1-0008\n"
            "```\n"
        )
        targets = (
            LinkTarget(
                "P1-0008",
                "actions/P1/P1-0008-create-stackgraph-model-tests.md",
                "actions/P1/P1-0008-create-stackgraph-model-tests.md",
            ),
            LinkTarget(
                "P2-0002",
                "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md",
                "actions/P2/P2-0002-create-mermaid-parser-package-boundary.md",
            ),
            LinkTarget(
                "P8-0020",
                "actions/P8/P8-0020-add-docs-freshness-test.md",
                "actions/P8/P8-0020-add-docs-freshness-test.md",
            ),
        )
        linked = _smart_link_markdown(
            markdown,
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            "actions/P2/P2-0001-define-mermaid-source-contract-document.md",
            targets,
            16,
        )
        self.assertIn(
            "[`P1-0008`](../P1/P1-0008-create-stackgraph-model-tests.md)", linked
        )
        self.assertIn(
            "[`P2-0002`](P2-0002-create-mermaid-parser-package-boundary.md)", linked
        )
        self.assertIn("[`P8-0020`](../P8/P8-0020-add-docs-freshness-test.md)", linked)
        self.assertIn("action: P1-0008", linked)


if __name__ == "__main__":
    unittest.main()
