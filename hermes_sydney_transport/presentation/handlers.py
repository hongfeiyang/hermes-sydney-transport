"""Generic Hermes handler generation from ToolSpec contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from ..application.capabilities import Capability
from .envelopes import execute
from .spec import ToolSpec

Dispatch = Callable[[Capability, BaseModel], BaseModel | Mapping[str, object]]
HermesHandler = Callable[..., str]


def handler_for(spec: ToolSpec, dispatch: Dispatch) -> HermesHandler:
    """Create the sole supported handler shape for one catalog entry."""

    def handler(args: dict[str, Any], **kwargs: Any) -> str:
        return execute(
            spec.input_model,
            spec.output_model,
            args,
            lambda request: dispatch(spec.capability, request),
        )

    handler.__name__ = spec.capability.value
    return handler
