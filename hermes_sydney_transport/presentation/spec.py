"""Single declarative extension contract for all Hermes tools."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from ..application.capabilities import Capability
from ..models.outputs import PluginOutput


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Everything presentation and bootstrap need to expose one capability."""

    capability: Capability
    name: str
    toolset: str
    description: str
    input_model: type[BaseModel]
    output_model: type[PluginOutput]
    requires_realtime: bool = False

    def schema(self) -> dict[str, object]:
        parameters = self.input_model.model_json_schema(mode="validation")
        parameters.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }
