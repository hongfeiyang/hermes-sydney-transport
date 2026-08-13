from __future__ import annotations

import importlib.util
import sys
import tomllib
import types
import unittest
from pathlib import Path

from hermes_sydney_transport import __version__

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_manifest_and_python_metadata_stay_aligned(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertIn("name: sydney-transport", manifest)
        self.assertIn('version: "0.5.0"', manifest)
        self.assertEqual(project["project"]["name"], "hermes-sydney-transport")
        self.assertEqual(project["project"]["version"], "0.5.0")
        self.assertEqual(__version__, project["project"]["version"])
        self.assertEqual(
            project["project"]["dependencies"],
            ["pydantic>=2.9,<3", "protobuf>=6.31,<8"],
        )
        self.assertEqual(
            project["project"]["entry-points"]["hermes_agent.plugins"][
                "sydney-transport"
            ],
            "hermes_sydney_transport",
        )

    def test_root_directory_shim_loads_like_hermes_namespace_package(self):
        parent = types.ModuleType("hermes_plugins")
        parent.__path__ = []
        sys.modules["hermes_plugins"] = parent
        module_name = "hermes_plugins.sydney_transport_contract_test"
        spec = importlib.util.spec_from_file_location(
            module_name,
            ROOT / "__init__.py",
            submodule_search_locations=[str(ROOT)],
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            self.assertTrue(callable(module.register))
        finally:
            sys.modules.pop(module_name, None)
            sys.modules.pop("hermes_plugins", None)


if __name__ == "__main__":
    unittest.main()
