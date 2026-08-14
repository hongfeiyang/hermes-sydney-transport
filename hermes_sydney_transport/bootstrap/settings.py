"""Validated deployment settings read only at the composition root."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..models.errors import DomainError


@dataclass(frozen=True)
class Settings:
    tfnsw_api_key: str
    cache_directory: Path

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if environment is None else environment
        key = source.get("TFNSW_API_KEY", "").strip()
        if not key:
            raise DomainError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        hermes_home = Path(source.get("HERMES_HOME", "~/.hermes")).expanduser()
        return cls(
            tfnsw_api_key=key,
            cache_directory=hermes_home / "cache" / "sydney-transport",
        )

    @classmethod
    def is_available(cls, environment: Mapping[str, str] | None = None) -> bool:
        source = os.environ if environment is None else environment
        return bool(source.get("TFNSW_API_KEY", "").strip())
