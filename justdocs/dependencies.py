"""Parse and check explicit artifact prerequisites in Markdown declarations."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Iterable

from justdocs.references import (
    FENCE_PATTERN,
    HEADING_PATTERN,
    REFERENCE_HEADING_PATTERN,
    REFERENCE_ID_PATTERN,
)

FIELD_PATTERN = re.compile(r"^(?:- )?\*\*(\w+):\*\*[ \t]*(.*)$", re.MULTILINE)
REQUIRED_FIELDS = frozenset({"Owner", "Requires", "Scope", "Produces", "Verify"})
SCOPE_RANK = MappingProxyType({"shared": 0, "build": 1, "target": 2})
TARGET_PATTERN = re.compile(r"[a-z][a-z0-9-]*")


class DependencyError(ValueError):
    """Report an invalid artifact dependency declaration or graph."""


@dataclass(frozen=True)
class DependencyNode:
    """Store one artifact boundary and its required verification."""

    id: str
    title: str
    requires: tuple[str, ...]
    owner: str
    scope: str
    produces: str
    verify: str
    source: str
    line: int


def parse_dependencies(markdown: str, source: str) -> tuple[DependencyNode, ...]:
    """Read metadata attached to each reference heading outside fenced code.

    Raises DependencyError for missing fields, malformed IDs or duplicate metadata.
    Metadata belongs to its immediately preceding heading, excluding nested sections.
    """
    content = FENCE_PATTERN.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match[0]),
        markdown,
    )
    headings = tuple(HEADING_PATTERN.finditer(content))
    nodes: list[DependencyNode] = []
    line = 1
    cursor = 0
    for index, heading in enumerate(headings):
        line += content.count("\n", cursor, heading.start())
        cursor = heading.start()
        declaration = REFERENCE_HEADING_PATTERN.fullmatch(heading[2])
        if declaration is None:
            continue
        node_id = declaration["id"].upper()
        location = f"{source}:{line} ({node_id})"
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        fields: dict[str, str] = {}
        for field in FIELD_PATTERN.finditer(content, heading.end(), end):
            name, value = field.groups()
            if name not in REQUIRED_FIELDS:
                continue
            if name in fields:
                raise DependencyError(f"duplicate {name} at {location}")
            fields[name] = value.strip()
        missing = sorted(name for name in REQUIRED_FIELDS if not fields.get(name))
        if missing:
            raise DependencyError(f"missing {', '.join(missing)} at {location}")
        requires = () if fields["Requires"] == "None" else tuple(
            item.strip().upper() for item in fields["Requires"].split(",")
        )
        if any(REFERENCE_ID_PATTERN.fullmatch(item) is None for item in requires):
            raise DependencyError(f"invalid Requires at {location}: expected IDs or None")
        if len(set(requires)) != len(requires):
            raise DependencyError(f"duplicate prerequisite at {location}")
        if fields["Scope"] not in SCOPE_RANK:
            raise DependencyError(f"invalid Scope at {location}: expected shared, build or target")
        nodes.append(DependencyNode(
            node_id, declaration["title"], requires, fields["Owner"], fields["Scope"],
            fields["Produces"], fields["Verify"], source,
            line,
        ))
    return tuple(nodes)


def _cycle_path(graph: dict[str, tuple[str, ...]], blocked: set[str]) -> str:
    visited: set[str] = set()
    for root in sorted(blocked):
        if root in visited:
            continue
        path = [root]
        active = {root: 0}
        stack = [iter(graph[root])]
        visited.add(root)
        while stack:
            child = next(stack[-1], None)
            if child is None:
                active.pop(path.pop())
                stack.pop()
            elif child in active:
                return " -> ".join(path[active[child]:] + [child])
            elif child in blocked and child not in visited:
                visited.add(child)
                active[child] = len(path)
                path.append(child)
                stack.append(iter(graph[child]))
    raise AssertionError("blocked dependency graph has no cycle")


def _topological_layers(graph: dict[str, tuple[str, ...]]) -> list[list[str]]:
    remaining = {node: len(requires) for node, requires in graph.items()}
    consumers: dict[str, list[str]] = defaultdict(list)
    for node, requires in graph.items():
        for dependency in requires:
            consumers[dependency].append(node)
    ready = sorted(node for node, count in remaining.items() if count == 0)
    layers: list[list[str]] = []
    while ready:
        layers.append(ready)
        following = []
        for node in ready:
            del remaining[node]
            for consumer in consumers[node]:
                remaining[consumer] -= 1
                if remaining[consumer] == 0:
                    following.append(consumer)
        ready = sorted(following)
    if remaining:
        raise DependencyError(f"dependency cycle: {_cycle_path(graph, set(remaining))}")
    return layers


def dependency_report(
    nodes: Iterable[DependencyNode], targets: Iterable[str] = (),
) -> dict[str, object]:
    """Validate all prerequisites and return a deterministic expanded graph.

    Target nodes consume target prerequisites in the same named target only.
    Time: O(v log v + e). Space: O(v + e), after target expansion.
    Raises DependencyError for duplicate IDs, unknown inputs, scope inversion or cycles.
    """
    bindings = tuple(targets)
    if len(set(bindings)) != len(bindings) or any(
        not isinstance(target, str) or TARGET_PATTERN.fullmatch(target) is None
        for target in bindings
    ):
        raise DependencyError("invalid dependency_targets: expected unique lowercase target names")
    indexed: dict[str, DependencyNode] = {}
    for node in nodes:
        if node.id in indexed:
            previous = indexed[node.id]
            raise DependencyError(
                f"duplicate dependency id {node.id}: {previous.source}, {node.source}"
            )
        indexed[node.id] = node
    if not indexed:
        raise DependencyError("dependency validation requires at least one declared node")
    for node in indexed.values():
        if node.scope not in SCOPE_RANK:
            raise DependencyError(f"invalid scope {node.scope} for {node.id}")
        if node.scope == "target" and not bindings:
            raise DependencyError(f"target node {node.id} requires dependency_targets")
        for dependency in node.requires:
            if dependency not in indexed:
                raise DependencyError(f"unknown prerequisite {dependency} for {node.id}")
            if SCOPE_RANK[indexed[dependency].scope] > SCOPE_RANK[node.scope]:
                raise DependencyError(f"scope inversion: {node.id} requires {dependency}")
    graph: dict[str, tuple[str, ...]] = {}
    for node in sorted(indexed.values(), key=lambda item: item.id):
        for target in bindings if node.scope == "target" else (None,):
            instance = f"{node.id}@{target}" if target is not None else node.id
            graph[instance] = tuple(
                f"{dependency}@{target}" if indexed[dependency].scope == "target" else dependency
                for dependency in node.requires
            )
    layers = _topological_layers(graph)
    return {
        "schema": 1,
        "targets": list(bindings),
        "templates": [asdict(indexed[node]) for node in sorted(indexed)],
        "nodes": [{"id": node, "requires": list(requires)} for node, requires in graph.items()],
        "layers": layers,
        "order": [node for layer in layers for node in layer],
        "counts": {
            "templates": len(indexed), "nodes": len(graph),
            "edges": sum(len(requires) for requires in graph.values()), "layers": len(layers),
        },
    }
