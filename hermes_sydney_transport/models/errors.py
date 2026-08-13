"""Stable domain errors shared across ports, application, and presentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorCode = Literal[
    "ambiguous_service",
    "authentication_failed",
    "internal_error",
    "invalid_argument",
    "invalid_realtime_feed",
    "invalid_upstream_response",
    "missing_configuration",
    "realtime_feed_unavailable",
    "response_too_large",
    "service_not_found",
    "static_data_invalid",
    "static_data_unavailable",
    "unverified_cancellation",
    "upstream_api_error",
    "upstream_http_error",
    "upstream_unavailable",
    "unsupported_dependency",
]


@dataclass(frozen=True)
class DomainError(Exception):
    """Safe error value that may cross an adapter/application boundary."""

    code: ErrorCode
    message: str
    retryable: bool = False
    http_status: int | None = None

    def __str__(self) -> str:
        return self.message
