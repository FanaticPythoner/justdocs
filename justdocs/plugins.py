"""Provide MkDocs content processors for the justdocs theme."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from markdown.extensions.toc import slugify
from mkdocs.config import config_options
from mkdocs.exceptions import PluginError
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import File

from justdocs.dependencies import (
    DependencyError,
    DependencyNode,
    dependency_report,
    parse_dependencies,
)
from justdocs.references import (
    FENCE_PATTERN,
    HEADING_PATTERN,
    REFERENCE_HEADING_PATTERN,
    REFERENCE_ID_PATTERN,
)


class JustdocsLinkerError(PluginError):
    """Report invalid justdocs-linker input state."""


@dataclass(frozen=True)
class LinkTarget:
    """Store one resolvable content phrase."""

    phrase: str
    url: str
    src_path: str


@dataclass(frozen=True)
class CompiledLinkTarget:
    """Store one link target with its normalized match key."""

    target: LinkTarget
    key: str
    pattern_text: str


@dataclass(frozen=True)
class CompiledLinkGraph:
    """Store compiled smart-link targets."""

    targets: tuple[CompiledLinkTarget, ...]
    targets_by_key: dict[str, LinkTarget]
    pattern: re.Pattern[str] | None


ACTION_ID_PATTERN = re.compile(r"\bP\d+-\d{4}\b", re.IGNORECASE)
ACTION_STEM_PATTERN = re.compile(r"^(?P<id>P\d+-\d{4})-(?P<title>.+)$", re.IGNORECASE)
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]+`")
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]\n]+]\([^)]+?\)")
REFERENCE_LINK_PATTERN = re.compile(r"!?\[[^\]\n]+]\[[^\]\n]*]")
REFERENCE_DEF_PATTERN = re.compile(r"(?m)^\[[^\]\n]+]:[^\n]+$")
HTML_TAG_PATTERN = re.compile(r"<[^>\n]+>")
ATX_HEADING_LINE_PATTERN = re.compile(r"(?m)^#{1,6}[ \t]+.+$")
MARKDOWN_DECORATION_PATTERN = re.compile(r"[*_~]+")
INLINE_LINK_TEXT_PATTERN = re.compile(r"!?\[([^\]\n]+)]\([^)]+?\)")
INLINE_CODE_TEXT_PATTERN = re.compile(r"`([^`\n]+)`")
WHITESPACE_PATTERN = re.compile(r"\s+")

STOP_PHRASES = frozenset(
    {
        "about",
        "api",
        "cli",
        "configuration",
        "example",
        "examples",
        "home",
        "index",
        "introduction",
        "overview",
        "reference",
        "references",
        "summary",
    },
)


def _normalize_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _phrase_key(value: str) -> str:
    return _normalize_text(value).casefold()


def _clean_heading_text(value: str) -> str:
    text = INLINE_LINK_TEXT_PATTERN.sub(r"\1", value)
    text = INLINE_CODE_TEXT_PATTERN.sub(r"\1", text)
    text = MARKDOWN_DECORATION_PATTERN.sub("", text)
    return _normalize_text(text.strip("# "))


def _title_from_stem(path: str) -> str:
    stem = Path(path).stem
    action_match = ACTION_STEM_PATTERN.match(stem)
    if action_match:
        title = re.sub(r"[-_]+", " ", action_match.group("title")).title()
        return f"{action_match.group('id').upper()} - {_normalize_text(title)}"
    return _normalize_text(re.sub(r"[-_]+", " ", stem).title())


def _dash_normalized_text(value: str) -> str:
    return _normalize_text(value.translate({0x2013: "-", 0x2014: "-"}))


def _is_eligible_phrase(value: str, min_phrase_chars: int) -> bool:
    phrase = _normalize_text(value)
    key = phrase.casefold()
    if len(phrase) < min_phrase_chars and not REFERENCE_ID_PATTERN.fullmatch(phrase):
        return False
    if key in STOP_PHRASES:
        return False
    if not any(character.isalpha() for character in phrase):
        return False
    return True


def _heading_targets(markdown: str, src_path: str) -> Iterable[LinkTarget]:
    for match in HEADING_PATTERN.finditer(FENCE_PATTERN.sub("", markdown)):
        level = len(match.group(1))
        title = _clean_heading_text(match.group(2))
        if not title:
            continue
        url = src_path if level == 1 else f"{src_path}#{slugify(title, '-', False)}"
        yield LinkTarget(title, url, src_path)


def _candidate_targets(markdown: str, src_path: str) -> Iterable[LinkTarget]:
    action_match = ACTION_ID_PATTERN.search(Path(src_path).stem)
    if action_match:
        yield LinkTarget(action_match.group(0).upper(), src_path, src_path)

    headings = tuple(_heading_targets(markdown, src_path))
    title = headings[0].phrase if headings else ""
    if title:
        yield LinkTarget(title, src_path, src_path)
        normalized_title = _dash_normalized_text(title)
        if normalized_title != title:
            yield LinkTarget(normalized_title, src_path, src_path)
    yield LinkTarget(_title_from_stem(src_path), src_path, src_path)
    for target in headings:
        reference = REFERENCE_HEADING_PATTERN.fullmatch(target.phrase)
        if reference:
            yield LinkTarget(reference.group("id").upper(), target.url, src_path)
            yield LinkTarget(reference.group("title"), target.url, src_path)
        yield target


def _dedupe_targets(
    targets: Iterable[LinkTarget], min_phrase_chars: int
) -> tuple[LinkTarget, ...]:
    by_key: dict[str, LinkTarget] = {}
    ambiguous: set[str] = set()
    for target in targets:
        phrase = _normalize_text(target.phrase)
        if not _is_eligible_phrase(phrase, min_phrase_chars):
            continue
        key = _phrase_key(phrase)
        normalized = LinkTarget(phrase, target.url, target.src_path)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = normalized
            continue
        if existing.url != normalized.url:
            if REFERENCE_ID_PATTERN.fullmatch(phrase):
                raise JustdocsLinkerError(
                    f"duplicate reference id {phrase}: {existing.url}, {normalized.url}"
                )
            ambiguous.add(key)

    return tuple(
        sorted(
            (target for key, target in by_key.items() if key not in ambiguous),
            key=lambda target: (
                -len(target.phrase),
                target.phrase.casefold(),
                target.url,
            ),
        ),
    )


def _target_pattern_text(phrase: str) -> str:
    parts = [re.escape(part) for part in _normalize_text(phrase).split()]
    return r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])"


def _target_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(_target_pattern_text(phrase), re.IGNORECASE)


def _compile_targets(targets: Iterable[LinkTarget]) -> CompiledLinkGraph:
    compiled = tuple(
        CompiledLinkTarget(
            target=target,
            key=_phrase_key(target.phrase),
            pattern_text=_target_pattern_text(target.phrase),
        )
        for target in targets
    )
    targets_by_key = {target.key: target.target for target in compiled}
    pattern = (
        re.compile(
            "|".join(f"(?:{target.pattern_text})" for target in compiled), re.IGNORECASE
        )
        if compiled
        else None
    )
    return CompiledLinkGraph(compiled, targets_by_key, pattern)


def _protected_ranges(
    markdown: str, include_inline_code: bool = True
) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    patterns = [
        FENCE_PATTERN,
        MARKDOWN_LINK_PATTERN,
        REFERENCE_LINK_PATTERN,
        REFERENCE_DEF_PATTERN,
        HTML_TAG_PATTERN,
        ATX_HEADING_LINE_PATTERN,
    ]
    if include_inline_code:
        patterns.append(INLINE_CODE_PATTERN)

    for pattern in patterns:
        ranges.extend(
            (match.start(), match.end()) for match in pattern.finditer(markdown)
        )
    return _merge_ranges(ranges)


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    ordered = sorted(ranges)
    if not ordered:
        return ()

    merged: list[tuple[int, int]] = []
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
            continue
        merged.append((start, end))
        start, end = next_start, next_end
    merged.append((start, end))
    return tuple(merged)


def _relative_url(current_url: str, target_url: str) -> str:
    target_path, separator, fragment = target_url.partition("#")
    if separator and target_path == current_url:
        return f"#{fragment}"
    current_base = (
        current_url if current_url.endswith("/") else posixpath.dirname(current_url)
    )
    current_base = current_base or "."
    target_for_relpath = target_path.rstrip("/") or "."
    relative = posixpath.relpath(target_for_relpath, current_base)
    if relative == ".":
        relative = ""
    if target_path.endswith("/") and relative and not relative.endswith("/"):
        relative = f"{relative}/"
    if separator:
        return f"{relative}#{fragment}"
    return relative or "."


def _is_linkable_target(target: LinkTarget, current_src_path: str) -> bool:
    return target.src_path != current_src_path or (
        REFERENCE_ID_PATTERN.fullmatch(target.phrase) is not None
        and "#" in target.url
    )


def _link_segment(
    segment: str,
    current_url: str,
    current_src_path: str,
    targets: CompiledLinkGraph,
    link_counts: dict[str, int],
    max_links_per_target: int,
    remaining_links: int,
) -> tuple[str, int]:
    cursor = 0
    linked = 0
    output: list[str] = []
    if targets.pattern is None:
        return segment, 0

    while cursor < len(segment) and linked < remaining_links:
        match = targets.pattern.search(segment, cursor)
        if match is None:
            break
        key = _phrase_key(match.group(0))
        target = targets.targets_by_key.get(key)

        output.append(segment[cursor : match.start()])
        if (
            target is None
            or not _is_linkable_target(target, current_src_path)
            or (
                not REFERENCE_ID_PATTERN.fullmatch(target.phrase)
                and link_counts.get(key, 0) >= max_links_per_target
            )
        ):
            output.append(match.group(0))
            cursor = match.end()
            continue

        href = _relative_url(current_url, target.url)
        output.append(f"[{match.group(0)}]({href})")
        link_counts[key] = link_counts.get(key, 0) + 1
        cursor = match.end()
        linked += 1

    output.append(segment[cursor:])
    return "".join(output), linked


def _target_by_exact_phrase(targets: CompiledLinkGraph) -> dict[str, LinkTarget]:
    return targets.targets_by_key


def _link_inline_code_segment(
    segment: str,
    current_url: str,
    current_src_path: str,
    targets_by_key: dict[str, LinkTarget],
    link_counts: dict[str, int],
    remaining_links: int,
) -> tuple[str, int]:
    linked = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal linked
        if linked >= remaining_links:
            return match.group(0)
        phrase = _normalize_text(match.group(0).strip("`"))
        if not REFERENCE_ID_PATTERN.fullmatch(phrase):
            return match.group(0)
        key = _phrase_key(phrase)
        target = targets_by_key.get(key)
        if target is None or not _is_linkable_target(target, current_src_path):
            return match.group(0)
        link_counts[key] = link_counts.get(key, 0) + 1
        linked += 1
        return f"[`{phrase}`]({_relative_url(current_url, target.url)})"

    return INLINE_CODE_PATTERN.sub(replace, segment), linked


def _link_inline_code_refs(
    markdown: str,
    current_url: str,
    current_src_path: str,
    targets: CompiledLinkGraph,
    link_counts: dict[str, int],
    max_links_per_page: int,
) -> tuple[str, int]:
    protected = _protected_ranges(markdown, include_inline_code=False)
    targets_by_key = _target_by_exact_phrase(targets)
    cursor = 0
    linked = 0
    output: list[str] = []

    for start, end in protected:
        segment, count = _link_inline_code_segment(
            markdown[cursor:start],
            current_url,
            current_src_path,
            targets_by_key,
            link_counts,
            max_links_per_page - linked,
        )
        output.append(segment)
        output.append(markdown[start:end])
        linked += count
        cursor = end
        if linked >= max_links_per_page:
            output.append(markdown[cursor:])
            return "".join(output), linked

    segment, count = _link_inline_code_segment(
        markdown[cursor:],
        current_url,
        current_src_path,
        targets_by_key,
        link_counts,
        max_links_per_page - linked,
    )
    output.append(segment)
    linked += count
    return "".join(output), linked


def _smart_link_markdown(
    markdown: str,
    current_src_path: str,
    current_url: str,
    targets: tuple[LinkTarget, ...] | CompiledLinkGraph,
    max_links_per_page: int,
    max_links_per_target: int = 2,
) -> str:
    compiled_targets = (
        targets if isinstance(targets, CompiledLinkGraph) else _compile_targets(targets)
    )
    link_counts: dict[str, int] = {}
    markdown, linked = _link_inline_code_refs(
        markdown,
        current_url,
        current_src_path,
        compiled_targets,
        link_counts,
        max_links_per_page,
    )
    protected = _protected_ranges(markdown)
    cursor = 0
    output: list[str] = []

    for start, end in protected:
        segment, count = _link_segment(
            markdown[cursor:start],
            current_url,
            current_src_path,
            compiled_targets,
            link_counts,
            max_links_per_target,
            max_links_per_page - linked,
        )
        output.append(segment)
        output.append(markdown[start:end])
        linked += count
        cursor = end
        if linked >= max_links_per_page:
            break

    if linked >= max_links_per_page:
        output.append(markdown[cursor:])
        return "".join(output)

    segment, _ = _link_segment(
        markdown[cursor:],
        current_url,
        current_src_path,
        compiled_targets,
        link_counts,
        max_links_per_target,
        max_links_per_page - linked,
    )
    output.append(segment)
    return "".join(output)


def _validate_linker_limits(config: Mapping[str, object]) -> None:
    """Validate positive smart-link bounds."""

    for name in ("min_phrase_chars", "max_links_per_page", "max_links_per_target"):
        value = config[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise JustdocsLinkerError(
                f"invalid {name} {value}: expected an integer greater than zero"
            )


class JustdocsLinkerPlugin(BasePlugin):
    """Insert deterministic cross-page links before Markdown rendering."""

    config_scheme = (
        ("enabled", config_options.Type(bool, default=True)),
        ("min_phrase_chars", config_options.Type(int, default=4)),
        ("max_links_per_page", config_options.Type(int, default=512)),
        ("max_links_per_target", config_options.Type(int, default=2)),
        ("validate_dependencies", config_options.Type(bool, default=False)),
        ("dependency_targets", config_options.ListOfItems(config_options.Type(str), default=[])),
    )

    def __init__(self) -> None:
        self._link_graph = _compile_targets(())

    def on_config(self, config):
        _validate_linker_limits(self.config)
        return config

    def on_files(self, files, config):
        if not self.config["enabled"] and not self.config["validate_dependencies"]:
            self._link_graph = _compile_targets(())
            return files

        candidates: list[LinkTarget] = []
        dependencies: list[DependencyNode] = []
        for file in files.documentation_pages():
            if not file.abs_src_path:
                raise JustdocsLinkerError(
                    f"documentation page missing source path: {file.src_path}"
                )
            markdown = Path(file.abs_src_path).read_text(encoding="utf-8")
            if self.config["enabled"]:
                candidates.extend(_candidate_targets(markdown, file.src_path))
            if self.config["validate_dependencies"]:
                try:
                    dependencies.extend(parse_dependencies(markdown, file.src_path))
                except DependencyError as error:
                    raise JustdocsLinkerError(str(error)) from error

        self._link_graph = _compile_targets(
            _dedupe_targets(candidates, self.config["min_phrase_chars"])
        )
        if self.config["validate_dependencies"]:
            try:
                report = dependency_report(dependencies, self.config["dependency_targets"])
            except DependencyError as error:
                raise JustdocsLinkerError(str(error)) from error
            if files.get_file_from_path("dependency-graph.json") is not None:
                raise JustdocsLinkerError("reserved dependency report path: dependency-graph.json")
            files.append(File.generated(
                config, "dependency-graph.json", content=json.dumps(report, indent=2) + "\n",
            ))
        return files

    def on_page_markdown(self, markdown, page, config, files):
        if not self.config["enabled"] or not self._link_graph.targets:
            return markdown
        return _smart_link_markdown(
            markdown,
            page.file.src_path,
            page.file.src_path,
            self._link_graph,
            self.config["max_links_per_page"],
            self.config["max_links_per_target"],
        )
