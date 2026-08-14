"""Typed contract for cached static-resource acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StaticDownload:
    not_modified: bool
    last_modified: datetime | None


class StaticResourceStore(Protocol):
    def download(
        self,
        resource: str,
        destination: Path,
        *,
        if_modified_since: datetime | None = None,
    ) -> StaticDownload: ...
