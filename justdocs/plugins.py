"""Provide MkDocs content processors for the justdocs theme."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from markdown.extensions.toc import slugify
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin


class JustdocsLinkerError(RuntimeError):
    """Report invalid justdocs-linker input state."""


@dataclass(frozen=True)
class LinkTarget:
    """Store one resolvable content phrase."""

    phrase: str
    url: str
    src_path: str


@dataclass(frozen=True)
class CompiledLinkTarget:
    """Store one link target with its matching automaton."""

    target: LinkTarget
    pattern: re.Pattern[str]


HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
ACTION_ID_PATTERN = re.compile(r"\bP\d+-\d{4}\b", re.IGNORECASE)
ACTION_STEM_PATTERN = re.compile(r"^(?P<id>P\d+-\d{4})-(?P<title>.+)$", re.IGNORECASE)
FENCE_PATTERN = re.compile(
    r"(?ms)^[ \t]{0,3}(?P<fence>`{3,}|~{3,}).*?^[ \t]{0,3}(?P=fence)[ \t]*$",
)
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
    if len(phrase) < min_phrase_chars:
        return False
    if key in STOP_PHRASES:
        return False
    if not any(character.isalpha() for character in phrase):
        return False
    return True


def _heading_targets(markdown: str, src_path: str) -> Iterable[LinkTarget]:
    for match in HEADING_PATTERN.finditer(markdown):
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

    title = next((target.phrase for target in _heading_targets(markdown, src_path)), "")
    if title:
        yield LinkTarget(title, src_path, src_path)
        normalized_title = _dash_normalized_text(title)
        if normalized_title != title:
            yield LinkTarget(normalized_title, src_path, src_path)
    yield LinkTarget(_title_from_stem(src_path), src_path, src_path)
    yield from _heading_targets(markdown, src_path)


def _dedupe_targets(targets: Iterable[LinkTarget], min_phrase_chars: int) -> tuple[LinkTarget, ...]:
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
            ambiguous.add(key)

    return tuple(
        sorted(
            (target for key, target in by_key.items() if key not in ambiguous),
            key=lambda target: (-len(target.phrase), target.phrase.casefold(), target.url),
        ),
    )


def _target_pattern(phrase: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in _normalize_text(phrase).split()]
    return re.compile(r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])", re.IGNORECASE)


def _compile_targets(targets: Iterable[LinkTarget]) -> tuple[CompiledLinkTarget, ...]:
    return tuple(CompiledLinkTarget(target, _target_pattern(target.phrase)) for target in targets)


def _protected_ranges(markdown: str, include_inline_code: bool = True) -> tuple[tuple[int, int], ...]:
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
        ranges.extend((match.start(), match.end()) for match in pattern.finditer(markdown))
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
    current_base = current_url if current_url.endswith("/") else posixpath.dirname(current_url)
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


def _link_segment(
    segment: str,
    current_url: str,
    current_src_path: str,
    targets: tuple[CompiledLinkTarget, ...],
    link_counts: dict[str, int],
    max_links_per_target: int,
    remaining_links: int,
) -> tuple[str, int]:
    cursor = 0
    linked = 0
    output: list[str] = []

    while cursor < len(segment) and linked < remaining_links:
        selected_match: re.Match[str] | None = None
        selected_target: LinkTarget | None = None
        for compiled in targets:
            target = compiled.target
            key = _phrase_key(target.phrase)
            if link_counts.get(key, 0) >= max_links_per_target or target.src_path == current_src_path:
                continue
            match = compiled.pattern.search(segment, cursor)
            if match is None:
                continue
            if selected_match is None or (match.start(), -len(target.phrase)) < (
                selected_match.start(),
                -len(selected_target.phrase) if selected_target else 0,
            ):
                selected_match = match
                selected_target = target

        if selected_match is None or selected_target is None:
            break

        output.append(segment[cursor : selected_match.start()])
        href = _relative_url(current_url, selected_target.url)
        output.append(f"[{selected_match.group(0)}]({href})")
        key = _phrase_key(selected_target.phrase)
        link_counts[key] = link_counts.get(key, 0) + 1
        cursor = selected_match.end()
        linked += 1

    output.append(segment[cursor:])
    return "".join(output), linked


def _target_by_exact_phrase(targets: tuple[CompiledLinkTarget, ...]) -> dict[str, LinkTarget]:
    by_key: dict[str, LinkTarget] = {}
    for compiled in targets:
        by_key[_phrase_key(compiled.target.phrase)] = compiled.target
    return by_key


def _link_inline_code_segment(
    segment: str,
    current_url: str,
    current_src_path: str,
    targets_by_key: dict[str, LinkTarget],
    link_counts: dict[str, int],
    max_links_per_target: int,
    remaining_links: int,
) -> tuple[str, int]:
    linked = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal linked
        if linked >= remaining_links:
            return match.group(0)
        phrase = _normalize_text(match.group(0).strip("`"))
        if not ACTION_ID_PATTERN.fullmatch(phrase):
            return match.group(0)
        key = _phrase_key(phrase)
        target = targets_by_key.get(key)
        if target is None or target.src_path == current_src_path:
            return match.group(0)
        if link_counts.get(key, 0) >= max_links_per_target:
            return match.group(0)

        link_counts[key] = link_counts.get(key, 0) + 1
        linked += 1
        return f"[`{phrase}`]({_relative_url(current_url, target.url)})"

    return INLINE_CODE_PATTERN.sub(replace, segment), linked


def _link_inline_code_refs(
    markdown: str,
    current_url: str,
    current_src_path: str,
    targets: tuple[CompiledLinkTarget, ...],
    link_counts: dict[str, int],
    max_links_per_target: int,
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
            max_links_per_target,
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
        max_links_per_target,
        max_links_per_page - linked,
    )
    output.append(segment)
    linked += count
    return "".join(output), linked


def _smart_link_markdown(
    markdown: str,
    current_src_path: str,
    current_url: str,
    targets: tuple[LinkTarget, ...],
    max_links_per_page: int,
    max_links_per_target: int = 2,
) -> str:
    compiled_targets = _compile_targets(targets)
    link_counts: dict[str, int] = {}
    markdown, linked = _link_inline_code_refs(
        markdown,
        current_url,
        current_src_path,
        compiled_targets,
        link_counts,
        max_links_per_target,
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


class JustdocsLinkerPlugin(BasePlugin):
    """Insert deterministic cross-page links before Markdown rendering."""

    config_scheme = (
        ("enabled", config_options.Type(bool, default=True)),
        ("min_phrase_chars", config_options.Type(int, default=4)),
        ("max_links_per_page", config_options.Type(int, default=512)),
        ("max_links_per_target", config_options.Type(int, default=2)),
    )

    def __init__(self) -> None:
        self._targets: tuple[LinkTarget, ...] = ()

    def on_files(self, files, config):
        if not self.config["enabled"]:
            self._targets = ()
            return files

        candidates: list[LinkTarget] = []
        for file in files.documentation_pages():
            if not file.abs_src_path:
                raise JustdocsLinkerError(f"documentation page missing source path: {file.src_path}")
            markdown = Path(file.abs_src_path).read_text(encoding="utf-8")
            candidates.extend(_candidate_targets(markdown, file.src_path))

        self._targets = _dedupe_targets(candidates, self.config["min_phrase_chars"])
        return files

    def on_page_markdown(self, markdown, page, config, files):
        if not self.config["enabled"] or not self._targets:
            return markdown
        return _smart_link_markdown(
            markdown,
            page.file.src_path,
            page.file.src_path,
            self._targets,
            self.config["max_links_per_page"],
            self.config["max_links_per_target"],
        )
