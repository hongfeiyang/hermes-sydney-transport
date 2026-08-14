"""Shared TfNSW transport primitives."""

from .contracts import (
    EndpointSpec,
    HttpPayload,
    HttpTransport,
    QueryParams,
    QueryScalar,
    RetryPolicy,
)
from .http import TfnswHttpClient
from .resilience import capture_domain_error

__all__ = [
    "EndpointSpec",
    "HttpPayload",
    "HttpTransport",
    "QueryParams",
    "QueryScalar",
    "RetryPolicy",
    "TfnswHttpClient",
    "capture_domain_error",
]
