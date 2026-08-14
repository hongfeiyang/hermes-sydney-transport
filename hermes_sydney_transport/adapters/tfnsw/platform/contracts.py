"""Typed transport contracts shared by TfNSW infrastructure adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

_TFNSW_API_HOST = "api.transport.nsw.gov.au"
_TFNSW_PUBLIC_ORIGINS = (
    f"https://{_TFNSW_API_HOST}",
    "https://opendata.transport.nsw.gov.au",
)

type QueryScalar = str | int | float | bool | None
type QueryParams = (
    Mapping[str, QueryScalar | Sequence[QueryScalar]]
    | list[tuple[str, QueryScalar]]
    | tuple[tuple[str, QueryScalar], ...]
)


class EndpointSpec(BaseModel):
    """Validated immutable policy for one allowlisted TfNSW endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    url: str = Field(max_length=500)
    accept: str = Field(min_length=3, max_length=120)
    content_types: frozenset[str] = Field(min_length=1, max_length=6)
    max_bytes: int = Field(ge=1_024, le=1_000_000_000)
    timeout_seconds: float = Field(gt=0, le=180)
    allow_not_modified: bool = False
    authenticated: bool = True

    @field_validator("url")
    @classmethod
    def url_is_fixed_tfnsw_https(cls, value: str) -> str:
        if (
            not any(
                value == origin or value.startswith(f"{origin}/")
                for origin in _TFNSW_PUBLIC_ORIGINS
            )
            or "#" in value
        ):
            raise ValueError("endpoint must be a fixed TfNSW HTTPS URL")
        return value

    @field_validator("authenticated")
    @classmethod
    def authentication_is_api_origin_only(
        cls, value: bool, info: ValidationInfo
    ) -> bool:
        url = info.data.get("url")
        api_origin = f"https://{_TFNSW_API_HOST}"
        if (
            value
            and isinstance(url, str)
            and not (url == api_origin or url.startswith(f"{api_origin}/"))
        ):
            raise ValueError("authenticated endpoints must use the TfNSW API origin")
        return value

    @field_validator("content_types")
    @classmethod
    def content_types_are_normalized(cls, value: frozenset[str]) -> frozenset[str]:
        if any(item != item.casefold() or "/" not in item for item in value):
            raise ValueError("content types must be lowercase media types")
        return value


class RetryPolicy(BaseModel):
    """Bounded retry policy shared by every TfNSW endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_attempts: int = Field(default=3, ge=1, le=5)
    base_delay_seconds: float = Field(default=0.25, ge=0, le=2)
    max_delay_seconds: float = Field(default=5.0, ge=0, le=10)


@dataclass(frozen=True, slots=True)
class HttpPayload:
    body: bytes | None
    content_type: str | None
    last_modified: str | None
    not_modified: bool = False


class HttpTransport(Protocol):
    def fetch(
        self,
        endpoint: EndpointSpec,
        *,
        params: QueryParams | None = None,
        if_modified_since: str | None = None,
    ) -> HttpPayload: ...

    def download(
        self,
        endpoint: EndpointSpec,
        destination: Path,
        *,
        if_modified_since: str | None = None,
    ) -> HttpPayload: ...
