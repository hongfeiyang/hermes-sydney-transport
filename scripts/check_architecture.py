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
            self._check_mode_source_of_truth,
            self._check_explicit_port_types,
            self._check_no_typed_dicts,
            self._check_no_legacy_generic_syntax,
            self._check_port_record_shape,
            self._check_no_application_parsing,
            self._check_infrastructure_literals,
            self._check_adapter_layout,
            self._check_adapter_role_dependencies,
            self._check_adapter_explicit_types,
            self._check_wire_model_shape,
            self._check_wire_timestamp_ownership,
            self._check_adapter_boundary_imports,
            self._check_manual_adapter_parsing,
            self._check_exception_boundaries,
            self._check_application_dict_projections,
            self._check_module_size,
            self._check_function_complexity,
            self._check_adapter_module_size,
            self._check_adapter_function_complexity,
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
            (
                "ModeSpec",
                set(configured.get("mode_spec_callers", [])),
                "single-mode-registry",
                "transport modes may only be extended in the configured registry",
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

    def _check_mode_source_of_truth(self) -> list[Violation]:
        """Reject hand-maintained mode registries and per-mode bootstrap branches."""

        allowed = set(self.policy.get("extension", {}).get("mode_registry_callers", []))
        violations: list[Violation] = []
        for path in self.source_files():
            relative = path.relative_to(self.package).as_posix()
            if relative in allowed:
                continue
            tree = self._tree(path)
            mode_symbols, mode_modules = self._transport_mode_aliases(tree)
            for node in tree.body:
                value = (
                    node.value
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    else None
                )
                if value is not None and self._uses_transport_mode_member(
                    value, mode_symbols, mode_modules
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "single-mode-registry",
                            "mode-keyed declarations belong only in bootstrap/modes.py; "
                            "derive runtime lookups from MODE_SPECS",
                        )
                    )
            for node in ast.walk(tree):
                if not isinstance(node, (ast.If, ast.Match)):
                    continue
                selector = node.test if isinstance(node, ast.If) else node.subject
                if self._uses_transport_mode_member(
                    selector, mode_symbols, mode_modules
                ):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "single-mode-binding-path",
                            "bootstrap and repositories must iterate MODE_SPECS instead "
                            "of branching on TransportMode",
                        )
                    )
        return violations

    @staticmethod
    def _transport_mode_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
        symbols = {"TransportMode"}
        modules: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "TransportMode":
                        symbols.add(alias.asname or alias.name)
                    elif alias.name == "realtime":
                        modules.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith(".ports.realtime"):
                        modules.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        return symbols, modules

    @staticmethod
    def _uses_transport_mode_member(
        node: ast.AST, symbols: set[str], modules: set[str]
    ) -> bool:
        return any(
            isinstance(child, ast.Attribute)
            and (
                isinstance(child.value, ast.Name)
                and child.value.id in symbols
                or isinstance(child.value, ast.Attribute)
                and child.value.attr == "TransportMode"
                and isinstance(child.value.value, ast.Name)
                and child.value.value.id in modules
            )
            for child in ast.walk(node)
        )

    def _check_explicit_port_types(self) -> list[Violation]:
        forbidden_layers = set(
            self.policy.get("extension", {}).get("forbid_any_layers", [])
        )
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) not in forbidden_layers:
                continue
            for node, dynamic_type in self._dynamic_type_references(path):
                if dynamic_type == "Any":
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
            for node, dynamic_type in self._dynamic_type_references(path):
                if dynamic_type == "TypedDict":
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

    def _check_adapter_layout(self) -> list[Violation]:
        """Require every provider module to occupy one declared internal role."""

        configured = self.policy.get("adapter_contract", {})
        if not configured:
            return []
        root = self.package / configured["root"]
        if not root.exists():
            return [
                Violation(
                    str(root.relative_to(self.root)),
                    "adapter-root",
                    "configured adapter root does not exist",
                )
            ]
        roles = set(configured.get("roles", []))
        allowed_root = set(configured.get("allowed_root_modules", []))
        violations: list[Violation] = []
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root)
            if len(relative.parts) == 1:
                if path.stem not in allowed_root:
                    violations.append(
                        Violation(
                            str(path.relative_to(self.root)),
                            "adapter-role-layout",
                            "provider modules must live under one declared adapter role",
                        )
                    )
                continue
            if relative.parts[0] not in roles:
                violations.append(
                    Violation(
                        str(path.relative_to(self.root)),
                        "adapter-role-layout",
                        f"unknown adapter role {relative.parts[0]!r}; expected one of "
                        f"{sorted(roles)}",
                    )
                )
        return violations

    def _check_adapter_role_dependencies(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        role_policy = self.policy.get("adapter_roles", {})
        if not configured or not role_policy:
            return []
        adapter_root = configured["root"].rstrip("/").replace("/", ".")
        violations: list[Violation] = []
        for path in self.source_files():
            role = self._adapter_role(path)
            if role is None:
                continue
            allowed = set(role_policy[role]["may_import"])
            for imported in self._internal_imports(path):
                if imported == adapter_root:
                    continue
                prefix = f"{adapter_root}."
                if not imported.startswith(prefix):
                    continue
                remainder = imported[len(prefix) :]
                imported_role = remainder.split(".", 1)[0]
                if imported_role not in role_policy:
                    violations.append(
                        Violation(
                            str(path.relative_to(self.root)),
                            "adapter-role-dependency",
                            f"{role} imports unstructured adapter module {imported!r}",
                        )
                    )
                elif imported_role not in allowed:
                    violations.append(
                        Violation(
                            str(path.relative_to(self.root)),
                            "adapter-role-dependency",
                            f"{role} may not import adapter role {imported_role!r}",
                        )
                    )
        return violations

    def _check_adapter_explicit_types(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        forbidden = set(configured.get("forbid_any_roles", []))
        violations: list[Violation] = []
        for path in self.source_files():
            if self._adapter_role(path) not in forbidden:
                continue
            for node, dynamic_type in self._dynamic_type_references(path):
                if dynamic_type in {"Any", "TypedDict"}:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "explicit-adapter-types",
                            "dynamic record types are confined to codec boundaries",
                        )
                    )
        return violations

    def _check_wire_model_shape(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        if not configured.get("require_pydantic_wire_models", False):
            return []
        adapter_root = self.package / configured["root"]
        wire_root = adapter_root / "wire"
        declarations: dict[str, tuple[Path, ast.ClassDef, set[str]]] = {}
        shared_roots = set(configured.get("wire_model_roots", ["WireModel"]))
        for path in sorted(wire_root.rglob("*.py")):
            for node in self._tree(path).body:
                if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                    continue
                bases = {
                    base.id
                    if isinstance(base, ast.Name)
                    else base.attr
                    if isinstance(base, ast.Attribute)
                    else ""
                    for base in node.bases
                }
                declarations[node.name] = path, node, bases

        def is_shared_wire(name: str, seen: frozenset[str] = frozenset()) -> bool:
            if name in shared_roots:
                return True
            if name in seen or name not in declarations:
                return False
            return any(
                is_shared_wire(base, seen | {name}) for base in declarations[name][2]
            )

        return [
            Violation(
                f"{path.relative_to(self.root)}:{node.lineno}",
                "pydantic-wire-contract",
                "public wire records must inherit from the shared Pydantic model family",
            )
            for name, (path, node, _) in declarations.items()
            if not is_shared_wire(name)
        ]

    def _check_wire_timestamp_ownership(self) -> list[Violation]:
        """Keep provider timestamp coercion behind one shared Pydantic contract."""

        configured = self.policy.get("adapter_contract", {})
        allowed = tuple(configured.get("wire_timestamp_paths", []))
        if not allowed:
            return []
        wire_root = self.package / configured["root"] / "wire"
        parsing_methods = {"fromisoformat", "fromtimestamp", "strptime"}
        parser_modules = {"arrow", "dateutil", "pendulum"}
        violations: list[Violation] = []
        for path in sorted(wire_root.rglob("*.py")):
            relative = path.relative_to(self.package).as_posix()
            if self._path_matches(relative, allowed):
                continue
            tree = self._tree(path)
            forbidden_imports = {
                imported
                for imported in self._external_imports(path)
                if imported.split(".", 1)[0] in parser_modules
            }
            if forbidden_imports:
                violations.append(
                    Violation(
                        str(path.relative_to(self.root)),
                        "single-wire-timestamp-contract",
                        "wire timestamp parsing belongs only in the configured "
                        f"timestamp contract: {sorted(forbidden_imports)}",
                    )
                )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                timestamp_adapter = (
                    called == "TypeAdapter"
                    and bool(node.args)
                    and any(
                        name in ast.unparse(node.args[0])
                        for name in ("datetime", "AwareDatetime")
                    )
                )
                if called in parsing_methods or timestamp_adapter:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "single-wire-timestamp-contract",
                            "wire models declare shared timestamp types; timestamp "
                            "normalization belongs only in wire/timestamps.py",
                        )
                    )
        return violations

    def _check_adapter_boundary_imports(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        if not configured:
            return []
        boundaries = (
            (
                "network_paths",
                ("http", "httpx", "requests", "urllib", "aiohttp"),
                "single-network-boundary",
                "network libraries belong only in the configured transport module",
            ),
            (
                "json_paths",
                ("json",),
                "single-json-codec",
                "JSON parsing belongs only in the configured JSON codec",
            ),
            (
                "csv_paths",
                ("csv",),
                "single-csv-codec",
                "CSV parsing belongs only in the configured CSV codec",
            ),
            (
                "archive_paths",
                ("zipfile",),
                "single-archive-codec",
                "archive parsing belongs only in a configured archive codec",
            ),
            (
                "xml_paths",
                ("xml",),
                "single-xml-codec",
                "XML parsing belongs only in the configured XLSX codec",
            ),
            (
                "html_paths",
                ("html",),
                "single-html-codec",
                "HTML parsing belongs only in the configured rich-text codec",
            ),
            (
                "protobuf_paths",
                ("google.protobuf",),
                "single-protobuf-codec",
                "protobuf parsing belongs only in the configured protobuf codec",
            ),
        )
        adapter_root = self.package / configured["root"]
        violations: list[Violation] = []
        for path in sorted(adapter_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(self.package).as_posix()
            imports = self._external_imports(path)
            for paths_key, prefixes, rule, message in boundaries:
                allowed = tuple(configured.get(paths_key, []))
                matches = {
                    imported
                    for imported in imports
                    if any(
                        imported == prefix or imported.startswith(f"{prefix}.")
                        for prefix in prefixes
                    )
                }
                if matches and not self._path_matches(relative, allowed):
                    violations.append(
                        Violation(
                            str(path.relative_to(self.root)),
                            rule,
                            f"{message}: {sorted(matches)}",
                        )
                    )
            if not self._path_matches(
                relative, tuple(configured.get("network_paths", []))
            ):
                for node in ast.walk(self._tree(path)):
                    if not (
                        isinstance(node, ast.Constant) and isinstance(node.value, str)
                    ):
                        continue
                    lowered = node.value.casefold()
                    if "authorization" in lowered or "tfnsw_api_key" in lowered:
                        violations.append(
                            Violation(
                                f"{path.relative_to(self.root)}:{node.lineno}",
                                "single-auth-boundary",
                                "API-key header and secret handling belong only in the "
                                "configured transport module",
                            )
                        )
        return violations

    def _check_manual_adapter_parsing(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        forbidden_roles = set(configured.get("forbid_manual_parsing_roles", []))
        parsing_methods = {"decode", "split", "splitlines", "strptime"}
        parsing_constructors = {"HTMLParser"}
        violations: list[Violation] = []
        for path in self.source_files():
            if self._adapter_role(path) not in forbidden_roles:
                continue
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
                dict_projection = (
                    called == "model_validate"
                    and bool(node.args)
                    and isinstance(node.args[0], ast.Dict)
                )
                if called in parsing_methods | parsing_constructors or dict_projection:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "declarative-adapter-parsing",
                            "repositories and mappers consume typed values; byte/text "
                            "parsing and dict validation belong in codecs",
                        )
                    )
        return violations

    def _check_exception_boundaries(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        if not configured:
            return []
        allowed = tuple(configured.get("exception_paths", []))
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) == "generated":
                continue
            relative = path.relative_to(self.package).as_posix()
            if self._path_matches(relative, allowed):
                continue
            for node in ast.walk(self._tree(path)):
                if isinstance(node, (ast.Try, ast.TryStar)):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "exception-boundary",
                            "try/except belongs only at declared transport, codec, "
                            "store, or presentation boundaries",
                        )
                    )
        return violations

    def _check_application_dict_projections(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        if not configured.get("forbid_application_dict_projection", False):
            return []
        violations: list[Violation] = []
        for path in self.source_files():
            if self._layer_for_path(path) != "application":
                continue
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                called = (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                )
                if called == "model_validate" and isinstance(node.args[0], ast.Dict):
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "typed-application-projection",
                            "application code must construct typed result/domain models; "
                            "nested dict projection is forbidden",
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

    def _check_adapter_module_size(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        maximum = int(self.policy.get("limits", {}).get("adapter_max_lines", 0))
        if not configured or maximum <= 0:
            return []
        repository_maximum = int(
            self.policy.get("limits", {}).get("adapter_repository_max_lines", maximum)
        )
        mapper_maximum = int(
            self.policy.get("limits", {}).get("adapter_mapper_max_lines", maximum)
        )
        adapter_root = self.package / configured["root"]
        violations: list[Violation] = []
        for path in sorted(adapter_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            role = self._adapter_role(path)
            limit = (
                repository_maximum
                if role == "repositories"
                else mapper_maximum
                if role == "mappers"
                else maximum
            )
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > limit:
                violations.append(
                    Violation(
                        str(path.relative_to(self.root)),
                        "adapter-module-size",
                        f"adapter module has {count} lines; maximum for "
                        f"{role or 'unstructured'} modules is {limit}",
                    )
                )
        return violations

    def _check_adapter_function_complexity(self) -> list[Violation]:
        configured = self.policy.get("adapter_contract", {})
        maximum = int(self.policy.get("limits", {}).get("adapter_max_complexity", 0))
        if not configured or maximum <= 0:
            return []
        adapter_root = self.package / configured["root"]
        violations: list[Violation] = []
        for path in sorted(adapter_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                complexity = self._complexity(node)
                if complexity > maximum:
                    violations.append(
                        Violation(
                            f"{path.relative_to(self.root)}:{node.lineno}",
                            "adapter-complexity",
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

    def _adapter_role(self, path: Path) -> str | None:
        configured = self.policy.get("adapter_contract", {})
        if not configured:
            return None
        adapter_root = self.package / configured["root"]
        try:
            relative = path.relative_to(adapter_root)
        except ValueError:
            return None
        if len(relative.parts) < 2:
            return None
        role = relative.parts[0]
        return role if role in set(configured.get("roles", [])) else None

    @staticmethod
    def _path_matches(relative: str, configured: tuple[str, ...]) -> bool:
        return any(
            relative == path.rstrip("/") or relative.startswith(f"{path.rstrip('/')}/")
            for path in configured
        )

    @staticmethod
    def _complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        branch_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match)
        descendants = [
            child
            for child in ast.walk(node)
            if child is not node
            and not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        complexity = 1 + sum(isinstance(child, branch_nodes) for child in descendants)
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
        return complexity

    def _relative_module(self, path: Path) -> str:
        relative = path.relative_to(self.package)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _internal_imports(self, path: Path) -> set[str]:
        imports: set[str] = set()
        for node in ast.walk(self._tree(path)):
            imports.update(self._internal_import_names(path, node))
        return imports

    def _internal_import_names(self, path: Path, node: ast.AST) -> set[str]:
        if isinstance(node, ast.Import):
            return {
                relative
                for alias in node.names
                if (relative := self._absolute_internal_name(alias.name)) is not None
            }
        if not isinstance(node, ast.ImportFrom):
            return set()
        target = node.module or ""
        if node.level:
            module = self._relative_module(path)
            current_package = (
                module.split(".")
                if path.name == "__init__.py" and module
                else module.split(".")[:-1]
            )
            keep = len(current_package) - (node.level - 1)
            if keep < 0:
                return set()
            parts = [*current_package[:keep], *target.split(".")]
            return {".".join(part for part in parts if part)}
        relative = self._absolute_internal_name(target)
        return {relative} if relative is not None else set()

    def _absolute_internal_name(self, module: str) -> str | None:
        if module == self.package_name:
            return ""
        prefix = f"{self.package_name}."
        return module[len(prefix) :] if module.startswith(prefix) else None

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

    def _dynamic_type_references(self, path: Path) -> list[tuple[ast.AST, str]]:
        """Resolve direct, aliased, qualified, and postponed Any/TypedDict uses."""

        tree = self._tree(path)
        typing_modules, names = self._typing_aliases(tree)
        references = self._resolved_dynamic_references(tree, typing_modules, names)
        return [*references, *self._postponed_dynamic_references(tree)]

    @staticmethod
    def _typing_aliases(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
        typing_modules = {"typing"}
        names = {"Any": "Any", "TypedDict": "TypedDict"}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"typing", "typing_extensions"}:
                        typing_modules.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "typing",
                "typing_extensions",
            }:
                for alias in node.names:
                    if alias.name in {"Any", "TypedDict"}:
                        names[alias.asname or alias.name] = alias.name
        return typing_modules, names

    @staticmethod
    def _resolved_dynamic_references(
        tree: ast.Module, typing_modules: set[str], names: dict[str, str]
    ) -> list[tuple[ast.AST, str]]:
        references: list[tuple[ast.AST, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names:
                references.append((node, names[node.id]))
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in typing_modules
                and node.attr in {"Any", "TypedDict"}
            ):
                references.append((node, node.attr))
        return references

    def _postponed_dynamic_references(
        self, tree: ast.Module
    ) -> list[tuple[ast.AST, str]]:
        references: list[tuple[ast.AST, str]] = []
        for annotation in self._annotations(tree):
            if not isinstance(annotation, ast.Constant) or not isinstance(
                annotation.value, str
            ):
                continue
            for dynamic_type in ("Any", "TypedDict"):
                if re.search(rf"\b{dynamic_type}\b", annotation.value):
                    references.append((annotation, dynamic_type))
        return references

    @staticmethod
    def _annotations(tree: ast.Module) -> list[ast.AST]:
        annotations: list[ast.AST] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) or (
                isinstance(node, ast.arg) and node.annotation is not None
            ):
                annotations.append(node.annotation)
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.returns is not None
            ):
                annotations.append(node.returns)
        return annotations

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
