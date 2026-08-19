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
        return cls(
            tfnsw_api_key=key,
            cache_directory=cls._cache_directory(source),
        )

    @staticmethod
    def _cache_directory(source: Mapping[str, str]) -> Path:
        """Resolve the GTFS cache directory.

        The cache is derived data — a ~540 MB `complete-gtfs.sqlite3` plus a
        facilities database, both rebuildable from the TfNSW feed. It is also
        identical for every profile on a host, because it describes the network,
        not the agent.

        Deriving it from ``HERMES_HOME`` is therefore wrong under a profile
        multiplexer: ``HERMES_HOME`` is whichever profile the gateway routed the
        turn to, so each profile that loads this plugin builds and stores its own
        half-gigabyte copy and re-downloads the whole feed to do it.

        ``SYDNEY_TRANSPORT_CACHE_DIR`` lets a deployment point every profile at
        one shared directory. Unset, the historical HERMES_HOME-relative path is
        used unchanged, so single-profile installs are unaffected.
        """
        override = source.get("SYDNEY_TRANSPORT_CACHE_DIR", "").strip()
        if override:
            return Path(override).expanduser()
        hermes_home = Path(source.get("HERMES_HOME", "~/.hermes")).expanduser()
        return hermes_home / "cache" / "sydney-transport"

    @classmethod
    def is_available(cls, environment: Mapping[str, str] | None = None) -> bool:
        source = os.environ if environment is None else environment
        return bool(source.get("TFNSW_API_KEY", "").strip())
