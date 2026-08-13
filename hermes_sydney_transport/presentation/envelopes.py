"""The single Hermes validation and JSON-envelope implementation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from pydantic import BaseModel, ValidationError

from ..models.errors import DomainError
from ..models.outputs import ErrorEnvelope, PluginOutput, SuccessEnvelope, ToolError

logger = logging.getLogger(__name__)


def execute[RequestT: BaseModel, ResultT: PluginOutput](
    input_model: type[RequestT],
    output_model: type[ResultT],
    args: Mapping[str, object],
    operation: Callable[[RequestT], BaseModel | Mapping[str, object]],
) -> str:
    """Validate once on each boundary and serialize the stable Hermes envelope."""

    try:
        request = input_model.model_validate(args)
    except ValidationError as exc:
        details: list[dict[str, object]] = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": error["msg"],
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]
        return error_json(
            DomainError("invalid_argument", "One or more tool arguments are invalid."),
            details=details,
        )

    try:
        result = operation(request)
        validated = output_model.model_validate(result)
        return SuccessEnvelope(
            data=validated.model_dump(mode="json", by_alias=True)
        ).model_dump_json(by_alias=True)
    except DomainError as exc:
        return error_json(exc)
    except ValidationError:
        logger.exception("Normalized output failed its Pydantic contract")
        return error_json(
            DomainError(
                "invalid_upstream_response",
                "TfNSW returned data that did not satisfy the plugin contract.",
            )
        )
    except Exception:
        logger.exception("Unexpected Sydney Transport plugin failure")
        return error_json(
            DomainError(
                "internal_error", "The Sydney Transport tool failed unexpectedly."
            )
        )


def error_json(
    error: DomainError,
    *,
    details: list[dict[str, object]] | None = None,
) -> str:
    return ErrorEnvelope(
        error=ToolError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            http_status=error.http_status,
            details=details,
        )
    ).model_dump_json(exclude_none=True)
