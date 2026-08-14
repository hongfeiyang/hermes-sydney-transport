"""Pydantic-core JSON decoding with one safe error translation."""

from __future__ import annotations

from pydantic import BaseModel, TypeAdapter, ValidationError

from ....models.errors import DomainError


class JsonModelCodec[ModelT: BaseModel]:
    """Compile and reuse one Pydantic JSON validator for a wire model."""

    def __init__(self, model: type[ModelT], *, source: str) -> None:
        self._adapter: TypeAdapter[ModelT] = TypeAdapter(model)
        self._source = source

    def decode(self, payload: bytes) -> ModelT:
        try:
            return self._adapter.validate_json(payload)
        except ValidationError as exc:
            raise DomainError(
                "invalid_upstream_response",
                f"TfNSW returned invalid {self._source} data.",
            ) from exc

    def __call__(self, payload: bytes) -> ModelT:
        return self.decode(payload)
