"""The only module authorized to register Hermes tools."""

from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel

from ..adapters.tfnsw.codecs import protobuf_available
from ..application.capabilities import Capability
from ..presentation.catalog import TOOL_SPECS
from ..presentation.handlers import handler_for
from .container import Container
from .settings import Settings


class _ContainerProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settings: Settings | None = None
        self._container: Container | None = None

    def get(self, settings: Settings) -> Container:
        with self._lock:
            if self._container is None or self._settings != settings:
                if self._container is not None:
                    self._container.close()
                self._container = Container(settings)
                self._settings = settings
            return self._container


_CONTAINERS = _ContainerProvider()


def _dispatch(capability: Capability, request: BaseModel) -> BaseModel:
    settings = Settings.from_environment()
    return _CONTAINERS.get(settings).execute(capability, request)


def _available(*, realtime: bool) -> bool:
    return Settings.is_available() and (not realtime or protobuf_available())


def register(ctx: Any) -> None:
    """Register every catalog entry through one audited Hermes call site."""

    for spec in TOOL_SPECS:
        ctx.register_tool(
            name=spec.name,
            toolset=spec.toolset,
            schema=spec.schema(),
            handler=handler_for(spec, _dispatch),
            check_fn=lambda realtime=spec.requires_realtime: _available(
                realtime=realtime
            ),
            requires_env=["TFNSW_API_KEY"],
        )
