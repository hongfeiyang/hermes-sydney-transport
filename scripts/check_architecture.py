#!/usr/bin/env python3
"""Validate the repository's machine-readable architecture contract."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.path}: [{self.rule}] {self.message}"


class ArchitectureChecker:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.policy = tomllib.loads(
            (self.root / "architecture.toml").read_text(encoding="utf-8")
        )
        self.package_name: str = self.policy["package"]
        self.package = self.root / self.package_name

    def check(self) -> list[Violation]:
        checks = (
            self._check_forbidden_paths,
            self._check_layer_ownership,
            self._check_root_modules,
            self._check_dependency_direction,
            self._check_capabilities,
            self._check_registration_calls,
            self._check_single_extension_path,
            self._check_explicit_port_types,
            self._check_no_typed_dicts,
            self._check_no_legacy_generic_syntax,
            self._check_port_record_shape,
            self._check_no_application_parsing,
            self._check_infrastructure_literals,
            self._check_module_size,
            self._check_function_complexity,
            self._check_nested_loops,
            self._check_raw_sql_boundary,
        )
        return [violation for check in checks for violation in check()]

    def _check_forbidden_paths(self) -> list[Violation]:
        violations: list[Violation] = []
        for configured in self.policy.get("repository", {}).get("forbidden_paths", []):
            path = self.root / configured
            if path.exists():
                violations.append(
                    Violation(
                        configured,
                        "forbidden-repository-path",
                        "legacy or parallel package paths must not be restored",
                    )
                )
        return violations

    def _check_no_legacy_generic_syntax(self) -> list[Violation]:
        if not self.policy.get("extension", {}).get(
            "forbid_legacy_generic_syntax", False
        ):
            return []
        violations: list[Violation] = []
        forbidden = {"Generic", "TypeVar"}
        for path in self.source_files():
            if self._layer_for_path(path) == "generated":
                continue
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module not in {"typing", "typing_extensions"}:
                    continue
                imported = forbidden.intersection(alias.name for alias in node.names)
                if imported:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "pep695-generics",
                            "use Python 3.12 type-parameter syntax instead of "
                            f"{sorted(imported)}",
                        )
                    )
        return violations

    def source_files(self) -> list[Path]:
        return sorted(
            path
            for path in self.package.rglob("*.py")
            if "__pycache__" not in path.parts
        )

    def _check_layer_ownership(self) -> list[Violation]:
        violations: list[Violation] = []
        owners: dict[str, str] = {}
        for layer, config in self.policy["layers"].items():
            for owned_path in config["paths"]:
                if owned_path in owners:
                    violations.append(
                        Violation(
                            "architecture.toml",
                            "unique-layer-owner",
                            f"{owned_path!r} belongs to {owners[owned_path]!r} and {layer!r}",
                        )
                    )
                owners[owned_path] = layer
        actual = {
            path.relative_to(self.package).parts[0]
            for path in self.source_files()
            if len(path.relative_to(self.package).parts) > 1
        }
        for unowned in sorted(actual - owners.keys()):
            violations.append(
                Violation(
                    str(self.package.relative_to(self.root) / unowned),
                    "layer-owner",
                    "top-level runtime package is not assigned to a layer",
                )
            )
        return violations

    def _check_root_modules(self) -> list[Violation]:
        configured = self.policy.get("root_modules", {})
        expected = set(configured.get("allowed", []))
        actual = {path.stem for path in self.package.glob("*.py")}
        if actual == expected:
            return []
        return [
            Violation(
                str(self.package.relative_to(self.root)),
                "root-modules",
                f"expected {sorted(expected)}, found {sorted(actual)}; runtime modules "
                "belong in a declared layer directory",
            )
        ]

    def _check_dependency_direction(self) -> list[Violation]:
        violations: list[Violation] = []
        for path in self.source_files():
            layer = self._layer_for_path(path)
            if layer is None or layer == "generated":
                continue
            allowed = set(self.policy["layers"][layer]["may_import"])
            dependencies = {
                dependency
                for module in self._internal_imports(path)
                if (dependency := self._layer_for_module(module)) is not None
            }
            forbidden = dependencies - allowed
            if forbidden:
                violations.append(
                    Violation(
                        str(path.relative_to(self.root)),
                        "dependency-direction",
                        f"{layer} may not import layers {sorted(forbidden)}",
                    )
                )
        return violations

    def _check_capabilities(self) -> list[Violation]:
        violations: list[Violation] = []
        capabilities: dict[str, list[str]] = self.policy["capabilities"]
        for path in self.source_files():
            layer = self._layer_for_path(path)
            if layer is None or layer == "generated":
                continue
            imports = self._external_imports(path)
            for capability in self.policy["layers"][layer]["forbidden_capabilities"]:
                prefixes = capabilities[capability]
                matches = {
                    imported
                    for imported in imports
                    if any(
                        imported == prefix or imported.startswith(f"{prefix}.")
                        for prefix in prefixes
                    )
                }
                if matches:
                    violations.append(
                        Violation(
                            str(path.relative_to(self.root)),
                            "forbidden-capability",
                            f"{layer} acquired {capability}: {sorted(matches)}",
                        )
                    )
        return violations

    def _check_registration_calls(self) -> list[Violation]:
        allowed = set(self.policy.get("extension", {}).get("registration_callers", []))
        if not allowed:
            return []
        violations: list[Violation] = []
        for path in self.source_files():
            relative = path.relative_to(self.package).as_posix()
            tree = self._tree(path)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register_tool"
                    and relative not in allowed
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "single-registration-path",
                            "only the configured bootstrap registrar may call register_tool",
                        )
                    )
        return violations

    def _check_raw_sql_boundary(self) -> list[Violation]:
        allowed_layers = set(
            self.policy.get("extension", {}).get("raw_sql_layers", ["adapters"])
        )
        violations: list[Violation] = []
        sql_pattern = re.compile(
            r"\b(?:select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from)\b",
            re.IGNORECASE | re.DOTALL,
        )
        for path in self.source_files():
            layer = self._layer_for_path(path)
            if layer is None or layer in allowed_layers or layer == "generated":
                continue
            for node in ast.walk(self._tree(path)):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and sql_pattern.search(node.value)
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "raw-sql-boundary",
                            "SQL-shaped strings are confined to adapters",
                        )
                    )
        return violations

    def _check_single_extension_path(self) -> list[Violation]:
        """Prevent parallel catalogs, schemas, or generated-handler paths."""

        configured = self.policy.get("extension", {})
        rules = (
            (
                "ToolSpec",
                set(configured.get("tool_spec_callers", [])),
                "single-tool-catalog",
                "ToolSpec entries may only be constructed in the configured catalog",
            ),
            (
                "model_json_schema",
                set(configured.get("schema_generation_callers", [])),
                "single-schema-path",
                "runtime JSON Schema generation belongs only in ToolSpec",
            ),
            (
                "handler_for",
                set(configured.get("handler_factory_callers", [])),
                "single-handler-path",
                "generic Hermes handlers may only be created by the registrar",
            ),
        )
        violations: list[Violation] = []
        for path in self.source_files():
            relative = path.relative_to(self.package).as_posix()
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, ast.Call):
                    continue
                called = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                for target, allowed, rule, message in rules:
                    if called == target and relative not in allowed:
                        violations.append(
                            Violation(
                                f"{path.relative_to(self.root)}:{node.lineno}",
                                rule,
                                message,
                            )
                        )
        return violations

    def _check_explicit_port_types(self) -> list[Violation]:
        forbidden_layers = set(
            self.policy.get("extension", {}).get("forbid_any_layers", [])
        )
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) not in forbidden_layers:
                continue
            for node in ast.walk(self._tree(path)):
                if isinstance(node, ast.Name) and node.id == "Any":
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "explicit-port-types",
                            "Any is forbidden in this layer; define an explicit type",
                        )
                    )
        return violations

    def _check_no_typed_dicts(self) -> list[Violation]:
        forbidden = set(
            self.policy.get("extension", {}).get("forbid_typed_dict_layers", [])
        )
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) not in forbidden:
                continue
            for node in ast.walk(self._tree(path)):
                if isinstance(node, ast.Name) and node.id == "TypedDict":
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "no-typed-dicts",
                            "TypedDict is forbidden here; use an immutable typed record",
                        )
                    )
        return violations

    def _check_port_record_shape(self) -> list[Violation]:
        required = set(
            self.policy.get("extension", {}).get("require_dataclass_records_layers", [])
        )
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) not in required:
                continue
            for node in self._tree(path).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = {ast.unparse(base).split("[", 1)[0] for base in node.bases}
                if base_names.intersection({"Protocol", "StrEnum", "Enum"}):
                    continue
                dataclass_decorator = next(
                    (
                        decorator
                        for decorator in node.decorator_list
                        if isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Name)
                        and decorator.func.id == "dataclass"
                    ),
                    None,
                )
                keywords = (
                    {item.arg: item.value for item in dataclass_decorator.keywords}
                    if dataclass_decorator
                    else {}
                )
                frozen = (
                    isinstance(keywords.get("frozen"), ast.Constant)
                    and keywords["frozen"].value is True
                )
                slotted = (
                    isinstance(keywords.get("slots"), ast.Constant)
                    and keywords["slots"].value is True
                )
                if not (frozen and slotted):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "immutable-port-record",
                            "port records must be explicit frozen, slotted dataclasses",
                        )
                    )
        return violations

    def _check_no_application_parsing(self) -> list[Violation]:
        forbidden = set(
            self.policy.get("extension", {}).get("forbid_time_parsing_layers", [])
        )
        parsing_calls = {"fromisoformat", "fromtimestamp", "strptime"}
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) not in forbidden:
                continue
            for node in ast.walk(self._tree(path)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in parsing_calls
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "typed-time-boundary",
                            "application receives typed dates and datetimes; parsing belongs in adapters",
                        )
                    )
        return violations

    def _check_infrastructure_literals(self) -> list[Violation]:
        extension = self.policy.get("extension", {})
        allowed = set(extension.get("infrastructure_literal_layers", ["adapters"]))
        literals = set(extension.get("infrastructure_literals", []))
        violations: list[Violation] = []
        for path in self.source_files():
            layer = self._layer_for_path(path)
            if layer is None or layer in allowed or layer == "generated":
                continue
            for node in ast.walk(self._tree(path)):
                if isinstance(node, ast.Constant) and node.value in literals:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "infrastructure-literal-boundary",
                            "feed endpoint identifiers belong only in adapters",
                        )
                    )
        return violations

    def _check_module_size(self) -> list[Violation]:
        maximum = int(self.policy.get("limits", {}).get("application_max_lines", 0))
        if maximum <= 0:
            return []
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) != "application":
                continue
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > maximum:
                violations.append(
                    Violation(
                        str(path.relative_to(self.root)),
                        "application-module-size",
                        f"application module has {count} lines; maximum is {maximum}",
                    )
                )
        return violations

    def _check_function_complexity(self) -> list[Violation]:
        maximum = int(
            self.policy.get("limits", {}).get("application_max_complexity", 0)
        )
        if maximum <= 0:
            return []
        violations: list[Violation] = []
        branch_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match)
        for path in self.source_files():
            if self._layer_for_path(path) != "application":
                continue
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                descendants = [
                    child
                    for child in ast.walk(node)
                    if child is not node
                    and not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                complexity = 1 + sum(
                    isinstance(child, branch_nodes) for child in descendants
                )
                complexity += sum(
                    max(len(child.values) - 1, 0)
                    for child in descendants
                    if isinstance(child, ast.BoolOp)
                )
                complexity += sum(
                    len(child.handlers) + bool(child.orelse)
                    for child in descendants
                    if isinstance(child, ast.Try)
                )
                if complexity > maximum:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "application-complexity",
                            f"{node.name} complexity is {complexity}; maximum is {maximum}",
                        )
                    )
        return violations

    def _check_nested_loops(self) -> list[Violation]:
        configured = tuple(
            self.policy.get("extension", {}).get("forbid_nested_loops_paths", [])
        )
        violations: list[Violation] = []
        loop_nodes = (ast.For, ast.AsyncFor, ast.While)
        for path in self.source_files():
            relative = path.relative_to(self.package).as_posix()
            if not any(
                relative == prefix or relative.startswith(f"{prefix}/")
                for prefix in configured
            ):
                continue
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, loop_nodes):
                    continue
                nested = any(
                    isinstance(child, loop_nodes)
                    for statement in node.body
                    for child in ast.walk(statement)
                )
                if nested:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "linear-realtime-iteration",
                            "realtime application loops may not contain nested loops; pre-index first",
                        )
                    )
        return violations

    def _layer_for_path(self, path: Path) -> str | None:
        relative = path.relative_to(self.package)
        if len(relative.parts) < 2:
            return None
        top = relative.parts[0]
        for name, config in self.policy["layers"].items():
            if top in config["paths"]:
                return name
        return None

    def _layer_for_module(self, module: str) -> str | None:
        top = module.split(".", 1)[0] if module else "__init__"
        for name, config in self.policy["layers"].items():
            if top in config["paths"]:
                return name
        return None

    def _relative_module(self, path: Path) -> str:
        relative = path.relative_to(self.package)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _internal_imports(self, path: Path) -> set[str]:
        tree = self._tree(path)
        module = self._relative_module(path)
        current_package = module.split(".")[:-1]
        if path.name == "__init__.py":
            current_package = module.split(".") if module else []
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == self.package_name:
                        imports.add("")
                    elif alias.name.startswith(f"{self.package_name}."):
                        imports.add(alias.name[len(self.package_name) + 1 :])
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if node.level:
                    keep = len(current_package) - (node.level - 1)
                    if keep < 0:
                        continue
                    parts = [*current_package[:keep], *target.split(".")]
                    imports.add(".".join(part for part in parts if part))
                elif target == self.package_name:
                    imports.add("")
                elif target.startswith(f"{self.package_name}."):
                    imports.add(target[len(self.package_name) + 1 :])
        return imports

    def _external_imports(self, path: Path) -> set[str]:
        imports: set[str] = set()
        for node in ast.walk(self._tree(path)):
            if isinstance(node, ast.Import):
                imports.update(
                    alias.name
                    for alias in node.names
                    if not alias.name.startswith(self.package_name)
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and not node.module.startswith(self.package_name)
            ):
                imports.add(node.module)
        return imports

    @staticmethod
    def _tree(path: Path) -> ast.Module:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repository_root())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    violations = ArchitectureChecker(args.root).check()
    if args.json:
        import json

        print(json.dumps([violation.__dict__ for violation in violations], indent=2))
    elif violations:
        print("Architecture contract violations:")
        for violation in violations:
            print(f"  - {violation.render()}")
    else:
        print("Architecture contract: OK")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
