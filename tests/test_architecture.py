from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_sydney_transport.application.capabilities import Capability
from hermes_sydney_transport.presentation.catalog import TOOL_SPECS
from scripts.check_architecture import ArchitectureChecker

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "hermes_sydney_transport"


class ArchitectureContractTests(unittest.TestCase):
    def test_machine_readable_architecture_contract_has_no_violations(self):
        self.assertEqual(ArchitectureChecker(ROOT).check(), [])

    def test_flat_runtime_modules_are_eliminated(self):
        self.assertEqual({path.name for path in PACKAGE.glob("*.py")}, {"__init__.py"})

    def test_catalog_is_complete_unique_and_schema_driven(self):
        self.assertEqual({spec.capability for spec in TOOL_SPECS}, set(Capability))
        self.assertEqual(len({spec.name for spec in TOOL_SPECS}), len(TOOL_SPECS))
        for spec in TOOL_SPECS:
            schema = spec.schema()
            self.assertEqual(schema["name"], spec.name)
            self.assertEqual(
                schema["parameters"],
                {
                    key: value
                    for key, value in spec.input_model.model_json_schema(
                        mode="validation"
                    ).items()
                    if key != "title"
                },
            )

    def test_checker_rejects_parallel_extension_paths_and_untyped_application(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy2(ROOT / "architecture.toml", root / "architecture.toml")
            shutil.copytree(PACKAGE, root / PACKAGE.name)
            (root / PACKAGE.name / "ports" / "illegal.py").write_text(
                "from typing import Any, TypedDict\n"
                "class Bad(TypedDict):\n    value: Any\n"
                "class LooseRecord:\n    value: str\n",
                encoding="utf-8",
            )
            (root / PACKAGE.name / "application" / "manual.py").write_text(
                "from datetime import datetime\n"
                "from typing import Any, TypeVar\n"
                "LegacyT = TypeVar('LegacyT')\n"
                "def parse(value: Any):\n"
                "    endpoint = 'trip_updates'\n"
                "    return datetime.fromisoformat(value), endpoint\n",
                encoding="utf-8",
            )
            (root / PACKAGE.name / "application" / "oversized.py").write_text(
                "# oversized\n" * 251,
                encoding="utf-8",
            )
            (root / PACKAGE.name / "application" / "complex.py").write_text(
                "def branch(value):\n"
                + "".join(
                    f"    if value == {index}:\n        return {index}\n"
                    for index in range(13)
                )
                + "    return -1\n",
                encoding="utf-8",
            )
            realtime = root / PACKAGE.name / "application" / "realtime"
            (realtime / "quadratic.py").write_text(
                "def compare(rows):\n"
                "    for left in rows:\n"
                "        for right in rows:\n"
                "            yield left, right\n",
                encoding="utf-8",
            )
            (root / PACKAGE.name / "presentation" / "parallel.py").write_text(
                "from .spec import ToolSpec\nspec = ToolSpec()\n",
                encoding="utf-8",
            )
            (root / "hermes_sydney_trains").mkdir()

            rules = {item.rule for item in ArchitectureChecker(root).check()}

        self.assertIn("forbidden-repository-path", rules)
        self.assertIn("explicit-port-types", rules)
        self.assertIn("no-typed-dicts", rules)
        self.assertIn("pep695-generics", rules)
        self.assertIn("immutable-port-record", rules)
        self.assertIn("typed-time-boundary", rules)
        self.assertIn("infrastructure-literal-boundary", rules)
        self.assertIn("application-module-size", rules)
        self.assertIn("application-complexity", rules)
        self.assertIn("linear-realtime-iteration", rules)
        self.assertIn("single-tool-catalog", rules)


if __name__ == "__main__":
    unittest.main()
