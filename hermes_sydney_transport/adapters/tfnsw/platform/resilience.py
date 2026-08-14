"""The single conversion boundary from DomainError to typed availability."""

from __future__ import annotations

from collections.abc import Callable

from ....models.availability import Availability, Unavailable
from ....models.errors import DomainError


def capture_domain_error[ValueT](
    operation: Callable[[], ValueT],
) -> Availability[ValueT]:
    try:
        return Availability(value=operation())
    except DomainError as exc:
        return Availability(
            value=None,
            unavailable=Unavailable(exc.code, exc.message, exc.retryable),
        )
