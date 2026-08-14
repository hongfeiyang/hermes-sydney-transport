from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_sydney_transport.application.capabilities import Capability
from hermes_sydney_transport.bootstrap.modes import MODE_SPECS
from hermes_sydney_transport.ports.realtime import TransportMode
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

    def test_mode_registry_is_complete_and_owns_realtime_capabilities(self):
        self.assertEqual({spec.mode for spec in MODE_SPECS}, set(TransportMode))
        capabilities = {
            capability
            for spec in MODE_SPECS
            for capability in (spec.service_status, spec.vehicle_position)
        }
        self.assertEqual(len(capabilities), len(MODE_SPECS) * 2)
        self.assertTrue(all(spec.policy.mode is spec.mode for spec in MODE_SPECS))
        self.assertTrue(
            all(
                len(spec.alert_sources) == len(spec.feeds.alerts)
                and all(spec.feeds.groups())
                for spec in MODE_SPECS
            )
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
                "class Result:\n"
                "    @classmethod\n"
                "    def model_validate(cls, value): return value\n"
                "def parse(value: Any):\n"
                "    endpoint = 'trip_updates'\n"
                "    projected = Result.model_validate({'value': value})\n"
                "    return datetime.fromisoformat(value), endpoint, projected\n",
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
                "from .spec import ToolSpec\nspec = ToolSpec()\nmode = ModeSpec()\n",
                encoding="utf-8",
            )
            (root / PACKAGE.name / "bootstrap" / "parallel_modes.py").write_text(
                "from ..ports.realtime import TransportMode as TM\n"
                "MODE_ENDPOINTS = {TM.TRAIN: 'alternate'}\n"
                "def bind(mode):\n"
                "    if mode is TM.TRAIN:\n"
                "        return 'special-case'\n",
                encoding="utf-8",
            )
            (root / "hermes_sydney_trains").mkdir()

            adapter_root = root / PACKAGE.name / "adapters" / "tfnsw"
            repositories = adapter_root / "repositories"
            codecs = adapter_root / "codecs"
            wire = adapter_root / "wire"
            mappers = adapter_root / "mappers"
            for path in (repositories, codecs, wire, mappers):
                path.mkdir(exist_ok=True)
                (path / "__init__.py").write_text("", encoding="utf-8")
            (adapter_root / "rogue.py").write_text("value = 1\n", encoding="utf-8")
            (repositories / "network.py").write_text(
                "from urllib.request import Request\n"
                "def fetch():\n"
                "    try:\n"
                "        return Request('https://example.invalid')\n"
                "    except OSError:\n"
                "        return None\n",
                encoding="utf-8",
            )
            (codecs / "alternate_json.py").write_text(
                "import json\ndef decode(value): return json.loads(value)\n",
                encoding="utf-8",
            )
            (wire / "wrong_way.py").write_text(
                "from ..repositories.network import fetch\n",
                encoding="utf-8",
            )
            (repositories / "oversized.py").write_text(
                "# oversized repository\n" * 201,
                encoding="utf-8",
            )
            (mappers / "complex.py").write_text(
                "def map_value(value):\n"
                + "".join(
                    f"    if value == {index}:\n        return {index}\n"
                    for index in range(11)
                )
                + "    return -1\n",
                encoding="utf-8",
            )

            violations = ArchitectureChecker(root).check()
            rules = {item.rule for item in violations}
            mode_rules = {
                item.rule
                for item in violations
                if item.path.split(":", 1)[0]
                == f"{PACKAGE.name}/bootstrap/parallel_modes.py"
            }

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
        self.assertTrue({"single-mode-registry", "single-mode-binding-path"} <= rules)
        self.assertEqual(
            mode_rules, {"single-mode-registry", "single-mode-binding-path"}
        )
        self.assertIn("typed-application-projection", rules)
        self.assertIn("adapter-role-layout", rules)
        self.assertIn("single-network-boundary", rules)
        self.assertIn("single-json-codec", rules)
        self.assertIn("exception-boundary", rules)
        self.assertIn("adapter-role-dependency", rules)
        self.assertIn("adapter-module-size", rules)
        self.assertIn("adapter-complexity", rules)

    def test_checker_rejects_untyped_non_pydantic_adapter_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy2(ROOT / "architecture.toml", root / "architecture.toml")
            shutil.copytree(PACKAGE, root / PACKAGE.name)
            adapter_root = root / PACKAGE.name / "adapters" / "tfnsw"
            (adapter_root / "wire" / "manual.py").write_text(
                "class ManualPayload:\n    value: dict\n",
                encoding="utf-8",
            )
            (adapter_root / "wire" / "manual_timestamp.py").write_text(
                "from datetime import datetime\n"
                "from typing import Annotated\n"
                "from pydantic import BeforeValidator\n"
                "def parse(value: str) -> datetime:\n"
                "    return datetime.fromisoformat(value)\n"
                "Timestamp = Annotated[datetime, BeforeValidator(parse)]\n",
                encoding="utf-8",
            )
            nested_wire = adapter_root / "wire" / "nested"
            nested_wire.mkdir()
            (nested_wire / "direct_base.py").write_text(
                "from pydantic import BaseModel\n"
                "class BypassPayload(BaseModel):\n    value: str\n",
                encoding="utf-8",
            )
            (adapter_root / "repositories" / "untyped.py").write_text(
                "import typing as t\nuntyped: t.Any = None\n",
                encoding="utf-8",
            )
            (adapter_root / "mappers" / "manual_parse.py").write_text(
                "from html.parser import HTMLParser as HP\n"
                "class Result:\n"
                "    @classmethod\n"
                "    def model_validate(cls, value): return value\n"
                "def parse(payload: bytes):\n"
                "    HP()\n"
                "    payload.decode(encoding='utf-8').split(',')\n"
                "    return Result.model_validate({'value': 1})\n",
                encoding="utf-8",
            )
            (adapter_root / "repositories" / "manual_parse.py").write_text(
                "def parse(raw: bytes):\n    return raw.decode('utf-8').split('\\n')\n",
                encoding="utf-8",
            )
            violations = ArchitectureChecker(root).check()
            rules = {item.rule for item in violations}
            parsing_paths = {
                item.path.split(":", 1)[0]
                for item in violations
                if item.rule == "declarative-adapter-parsing"
            }

        self.assertIn("explicit-adapter-types", rules)
        self.assertIn("pydantic-wire-contract", rules)
        self.assertIn("single-wire-timestamp-contract", rules)
        self.assertIn("declarative-adapter-parsing", rules)
        self.assertIn("single-html-codec", rules)
        self.assertIn(
            f"{PACKAGE.name}/adapters/tfnsw/mappers/manual_parse.py", parsing_paths
        )
        self.assertIn(
            f"{PACKAGE.name}/adapters/tfnsw/repositories/manual_parse.py",
            parsing_paths,
        )


if __name__ == "__main__":
    unittest.main()
