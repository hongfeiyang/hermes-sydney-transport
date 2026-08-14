"""Typed availability values for explicitly best-effort data joins."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ErrorCode


@dataclass(frozen=True, slots=True)
class Unavailable:
    code: ErrorCode
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class Availability[ValueT]:
    value: ValueT | None
    unavailable: Unavailable | None = None

    @property
    def is_available(self) -> bool:
        return self.unavailable is None
