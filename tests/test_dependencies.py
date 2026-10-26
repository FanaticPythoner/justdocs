from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from mkdocs.commands.build import build
from mkdocs.config import load_config
from mkdocs.exceptions import Abort

from justdocs.dependencies import DependencyError, dependency_report, parse_dependencies


def declaration(node: str, requires: str = "None", scope: str = "shared") -> str:
    return (
        f"## [{node}] Deliver artifact\n\n"
        "**Owner:** Component team\n"
        f"**Requires:** {requires}\n"
        f"**Scope:** {scope}\n"
        "**Produces:** Versioned artifact\n"
        "**Verify:** Pass conformance checks\n\n"
    )


def assert_build_error(test: unittest.TestCase, config, message: str) -> None:
    with test.assertLogs("mkdocs.commands.build", level="ERROR") as logs:
        with test.assertRaises(Abort):
            build(config)
    test.assertTrue(any(message in line for line in logs.output), logs.output)


class DependencyGraphTest(unittest.TestCase):
    def test_parse_preserves_locations_and_excludes_fenced_declarations(self) -> None:
        text = "```md\n" + declaration("X9") + "```\n\n" + declaration("T1")
        nodes = parse_dependencies(text, "team.md")
        self.assertEqual(["T1"], [node.id for node in nodes])
        self.assertEqual(text.splitlines().index("## [T1] Deliver artifact") + 1, nodes[0].line)
        self.assertEqual("team.md", nodes[0].source)

    def test_longer_closing_and_unclosed_fences_do_not_declare_nodes(self) -> None:
        for fence in ("```", "~~~"):
            text = fence + "md\n" + declaration("X9") + fence + fence[0] + "\n"
            self.assertEqual((), parse_dependencies(text, "t.md"))
            self.assertEqual((), parse_dependencies(fence + "\n" + declaration("X9"), "t.md"))

    def test_parse_rejects_missing_empty_and_duplicate_fields(self) -> None:
        text = declaration("T1")
        for field in ("Owner", "Requires", "Scope", "Produces", "Verify"):
            line = next(line for line in text.splitlines() if line.startswith(f"**{field}:"))
            for broken in (text.replace(line, ""), text.replace(line, f"**{field}:**")):
                with self.subTest(field=field, broken=broken):
                    with self.assertRaisesRegex(DependencyError, "missing " + field):
                        parse_dependencies(broken, "team.md")
            with self.assertRaisesRegex(DependencyError, "duplicate " + field):
                parse_dependencies(text + line + "\n", "team.md")

    def test_metadata_cannot_be_borrowed_from_nested_section(self) -> None:
        with self.assertRaisesRegex(DependencyError, "missing.*T1"):
            parse_dependencies("# [T1] Parent\n" + declaration("T2"), "team.md")

    def test_parse_rejects_prose_negation_and_duplicate_prerequisites(self) -> None:
        for value in ("T1 and F7", "None, T1", "not T1", "T1.", "", "T1, T1", "T1,"):
            with self.subTest(value=value), self.assertRaises(DependencyError):
                parse_dependencies(declaration("F1", value), "team.md")

    def test_parse_normalizes_ids_and_accepts_list_metadata(self) -> None:
        node = parse_dependencies(declaration("t1", "f7-1"), "t.md")[0]
        listed = parse_dependencies(declaration("T1", "F7-1").replace("**", "- **", 1), "t.md")[0]
        self.assertEqual("T1", node.id)
        self.assertEqual(("F7-1",), node.requires)
        self.assertEqual(node.requires, listed.requires)

    def test_invalid_scope_and_targets_are_explicit_errors(self) -> None:
        with self.assertRaisesRegex(DependencyError, "invalid Scope"):
            parse_dependencies(declaration("T1", scope="environment"), "t.md")
        node = parse_dependencies(declaration("T1"), "t.md")
        for targets in (("prod", "prod"), ("PROD",), ("prod@staging",), ("",)):
            with self.subTest(targets=targets), self.assertRaisesRegex(
                DependencyError, "dependency_targets"
            ):
                dependency_report(node, targets)

    def test_duplicate_ids_and_unknown_prerequisites_are_rejected(self) -> None:
        node = parse_dependencies(declaration("T1", "F7"), "t.md")[0]
        with self.assertRaisesRegex(DependencyError, "unknown prerequisite F7 for T1"):
            dependency_report((node,))
        with self.assertRaisesRegex(DependencyError, "duplicate dependency id T1"):
            dependency_report((node, node))
        with self.assertRaisesRegex(DependencyError, "at least one"):
            dependency_report(())

    def test_full_task_cycle_is_not_hidden_by_a_library_milestone(self) -> None:
        nodes = parse_dependencies(
            declaration("F7-1") + declaration("T1", "F7-1") + declaration("F7", "T1"),
            "team.md",
        )
        self.assertEqual(["F7-1", "T1", "F7"], dependency_report(nodes)["order"])
        broken = tuple(replace(node, requires=("F7",)) if node.id == "T1" else node for node in nodes)
        with self.assertRaisesRegex(DependencyError, r"dependency cycle: F7 -> T1 -> F7"):
            dependency_report(broken)

    def test_self_cycle_and_disconnected_cycle_are_rejected(self) -> None:
        for text in (
            declaration("T1", "T1"),
            declaration("T1") + declaration("T2", "T3") + declaration("T3", "T2"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(DependencyError, "cycle:"):
                dependency_report(parse_dependencies(text, "team.md"))

    def test_target_expansion_keeps_capacity_in_the_consuming_target(self) -> None:
        nodes = parse_dependencies(
            declaration("F1") + declaration("J1", "F1", "build")
            + declaration("M1", "J1", "target") + declaration("J2", "M1", "target"),
            "team.md",
        )
        report = dependency_report(nodes, ("dev", "staging", "prod"))
        graph = {node["id"]: node["requires"] for node in report["nodes"]}
        self.assertEqual(8, len(graph))
        self.assertEqual(["M1@prod"], graph["J2@prod"])
        self.assertEqual(["M1@dev"], graph["J2@dev"])
        self.assertEqual(["J1"], graph["M1@staging"])
        self.assertEqual(report, dependency_report(reversed(nodes), ("dev", "staging", "prod")))

    def test_scope_inversions_and_unbound_target_are_rejected(self) -> None:
        for scope in ("shared", "build"):
            nodes = parse_dependencies(
                declaration("T1", "M1", scope) + declaration("M1", scope="target"), "t.md"
            )
            with self.subTest(scope=scope), self.assertRaisesRegex(DependencyError, "scope inversion"):
                dependency_report(nodes, ("prod",))
        with self.assertRaisesRegex(DependencyError, "requires dependency_targets"):
            dependency_report(parse_dependencies(declaration("M1", scope="target"), "t.md"))
        with self.assertRaisesRegex(DependencyError, "scope inversion"):
            dependency_report(parse_dependencies(
                declaration("T1", "J1") + declaration("J1", scope="build"), "t.md"
            ))

    def test_all_three_node_graphs_match_independent_permutation_oracle(self) -> None:
        ids = ("T1", "T2", "T3")
        edges = tuple(itertools.permutations(ids, 2))
        base = parse_dependencies("".join(declaration(node) for node in ids), "t.md")
        for mask in range(1 << len(edges)):
            selected = tuple(edge for index, edge in enumerate(edges) if mask & (1 << index))
            orders = [
                order for order in itertools.permutations(ids)
                if all(order.index(prerequisite) < order.index(node) for node, prerequisite in selected)
            ]
            nodes = tuple(replace(node, requires=tuple(
                prerequisite for consumer, prerequisite in selected if consumer == node.id
            )) for node in base)
            with self.subTest(mask=mask):
                if not orders:
                    with self.assertRaises(DependencyError):
                        dependency_report(nodes)
                else:
                    self.assertIn(tuple(dependency_report(nodes)["order"]), orders)

    def test_long_cycle_avoids_recursion_and_reports_closed_path(self) -> None:
        base = parse_dependencies(declaration("T1"), "t.md")[0]
        nodes = tuple(replace(base, id=f"T{i}", requires=(f"T{(i + 1) % 1200}",))
                      for i in range(1200))
        with self.assertRaisesRegex(DependencyError, "dependency cycle: T0 -> T1"):
            dependency_report(nodes)

    def test_native_build_generates_report_and_links_dependency_sections(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs/index.md").write_text(
                "# Components\n\n" + declaration("F7-1") + declaration("T1", "F7-1")
                + "[Dependency graph](dependency-graph.json)\n", encoding="utf-8",
            )
            (root / "mkdocs.yml").write_text(
                "site_name: Dependencies\nstrict: true\ntheme: justdocs\nplugins:\n"
                "  - justdocs-linker:\n      validate_dependencies: true\n",
                encoding="utf-8",
            )
            config = load_config(config_file=str(root / "mkdocs.yml"))
            build(config)
            report = json.loads((root / "site/dependency-graph.json").read_text())
            self.assertEqual(["F7-1", "T1"], report["order"])
            self.assertIn('href="#f7-1-deliver-artifact"', (root / "site/index.html").read_text())
            (root / "docs/index.md").write_text(
                "# Components\n\n" + declaration("T1", "F7") + declaration("F7", "T1"),
                encoding="utf-8",
            )
            assert_build_error(self, config, "dependency cycle:")

    def test_native_validation_is_opt_in_independent_and_reserves_report_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            source = root / "docs/index.md"
            source.write_text("# [T1] Plain reference\n", encoding="utf-8")
            config_path = root / "mkdocs.yml"
            prefix = "site_name: Dependencies\nstrict: true\ntheme: justdocs\nplugins:\n"
            config_path.write_text(prefix + "  - justdocs-linker\n", encoding="utf-8")
            build(load_config(config_file=str(config_path)))
            self.assertFalse((root / "site/dependency-graph.json").exists())
            config_path.write_text(
                prefix + "  - justdocs-linker:\n      enabled: false\n"
                "      validate_dependencies: true\n", encoding="utf-8",
            )
            config = load_config(config_file=str(config_path))
            source.write_text(
                "# Components\n\n" + declaration("T1", "F7") + declaration("F7", "T1"),
                encoding="utf-8",
            )
            assert_build_error(self, config, "dependency cycle:")
            source.write_text("# Components\n\n" + declaration("T1"), encoding="utf-8")
            (root / "docs/dependency-graph.json").write_text("{}", encoding="utf-8")
            assert_build_error(self, config, "reserved dependency report path")

    def test_native_cli_reports_cycles_without_a_python_traceback(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs/index.md").write_text(
                "# Components\n\n" + declaration("T1", "F7") + declaration("F7", "T1"),
                encoding="utf-8",
            )
            (root / "mkdocs.yml").write_text(
                "site_name: Dependencies\nstrict: true\ntheme: justdocs\nplugins:\n"
                "  - justdocs-linker:\n      validate_dependencies: true\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "--strict", "--clean"],
                cwd=root, capture_output=True, text=True, check=False,
                env=os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("dependency cycle:", result.stderr)
            self.assertNotIn("Traceback", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
