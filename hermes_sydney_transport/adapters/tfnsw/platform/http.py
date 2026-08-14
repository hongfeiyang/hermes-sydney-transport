"""The sole authenticated HTTP and transport-error boundary for TfNSW."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from ....models.errors import DomainError
from ....models.metadata import USER_AGENT
from .contracts import (
    EndpointSpec,
    HttpPayload,
    HttpTransport,
    QueryParams,
    RetryPolicy,
)

_AUTH_FAILURES = frozenset({401, 403})
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class _RetryableStatus(Exception):
    status: int
    retry_after: str | None


class TfnswHttpClient(HttpTransport):
    """Persistent client applying one security, retry, and error policy."""

    def __init__(
        self,
        api_key: str,
        *,
        retry_policy: RetryPolicy | None = None,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise DomainError(
                "missing_configuration", "TFNSW_API_KEY is not configured."
            )
        self._api_key = api_key.strip()
        self._retry_policy = retry_policy or RetryPolicy()
        self._client = client or httpx.Client(
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
        self._owns_client = client is None
        self._sleeper = sleeper

    def fetch(
        self,
        endpoint: EndpointSpec,
        *,
        params: QueryParams | None = None,
        if_modified_since: str | None = None,
    ) -> HttpPayload:
        return self._run(lambda: self._fetch_once(endpoint, params, if_modified_since))

    def download(
        self,
        endpoint: EndpointSpec,
        destination: Path,
        *,
        if_modified_since: str | None = None,
    ) -> HttpPayload:
        destination.unlink(missing_ok=True)
        try:
            return self._run(
                lambda: self._download_once(endpoint, destination, if_modified_since)
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def _run[ResultT](self, operation: Callable[[], ResultT]) -> ResultT:
        retryer = Retrying(
            stop=stop_after_attempt(self._retry_policy.max_attempts),
            retry=retry_if_exception_type(
                (_RetryableStatus, httpx.TimeoutException, httpx.TransportError)
            ),
            wait=self._retry_delay,
            sleep=self._sleeper,
            reraise=True,
        )
        try:
            return retryer(operation)
        except _RetryableStatus as exc:
            raise DomainError(
                "upstream_http_error",
                f"TfNSW request failed with HTTP {exc.status}.",
                retryable=True,
                http_status=exc.status,
            ) from exc
        except httpx.TimeoutException as exc:
            raise DomainError(
                "upstream_unavailable",
                "TfNSW did not respond before the configured deadline.",
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise DomainError(
                "upstream_unavailable",
                "TfNSW could not be reached before retry attempts were exhausted.",
                retryable=True,
            ) from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _fetch_once(
        self,
        endpoint: EndpointSpec,
        params: QueryParams | None,
        if_modified_since: str | None,
    ) -> HttpPayload:
        headers = self._headers(endpoint, if_modified_since)
        query_params = httpx.QueryParams(params) if params is not None else None
        with self._client.stream(
            "GET",
            endpoint.url,
            headers=headers,
            params=query_params,
            timeout=endpoint.timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.status_code == 304 and endpoint.allow_not_modified:
                return self._payload(response, body=None, not_modified=True)
            self._validate_status(response)
            self._validate_content_type(endpoint, response)
            self._validate_declared_size(endpoint, response)
            return self._payload(
                response,
                body=self._read_bounded(endpoint, response),
                not_modified=False,
            )

    def _download_once(
        self,
        endpoint: EndpointSpec,
        destination: Path,
        if_modified_since: str | None,
    ) -> HttpPayload:
        with self._client.stream(
            "GET",
            endpoint.url,
            headers=self._headers(endpoint, if_modified_since),
            timeout=endpoint.timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.status_code == 304 and endpoint.allow_not_modified:
                return self._payload(response, body=None, not_modified=True)
            self._validate_status(response)
            self._validate_content_type(endpoint, response)
            self._validate_declared_size(endpoint, response)
            self._write_bounded(endpoint, response, destination)
            return self._payload(response, body=None, not_modified=False)

    def _headers(
        self, endpoint: EndpointSpec, if_modified_since: str | None
    ) -> dict[str, str]:
        headers = {"Accept": endpoint.accept}
        if endpoint.authenticated:
            headers["Authorization"] = f"apikey {self._api_key}"
        if if_modified_since is not None:
            headers["If-Modified-Since"] = if_modified_since
        return headers

    @staticmethod
    def _validate_status(response: httpx.Response) -> None:
        if response.status_code in _RETRYABLE_STATUS:
            raise _RetryableStatus(
                response.status_code, response.headers.get("Retry-After")
            )
        if response.status_code in _AUTH_FAILURES:
            raise DomainError(
                "authentication_failed",
                "TfNSW rejected the configured API credential.",
                http_status=response.status_code,
            )
        if response.is_error or response.is_redirect:
            raise DomainError(
                "upstream_http_error",
                f"TfNSW request failed with HTTP {response.status_code}.",
                http_status=response.status_code,
            )

    @staticmethod
    def _payload(
        response: httpx.Response, *, body: bytes | None, not_modified: bool
    ) -> HttpPayload:
        return HttpPayload(
            body=body,
            content_type=response.headers.get("Content-Type"),
            last_modified=response.headers.get("Last-Modified"),
            not_modified=not_modified,
        )

    @staticmethod
    def _validate_content_type(
        endpoint: EndpointSpec, response: httpx.Response
    ) -> None:
        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().casefold()
        if media_type not in endpoint.content_types:
            raise DomainError(
                "invalid_upstream_response",
                "TfNSW returned an unexpected response content type.",
                http_status=response.status_code,
            )

    @staticmethod
    def _validate_declared_size(
        endpoint: EndpointSpec, response: httpx.Response
    ) -> None:
        declared = response.headers.get("Content-Length")
        if (
            declared is not None
            and declared.isdecimal()
            and int(declared) > endpoint.max_bytes
        ):
            raise DomainError(
                "response_too_large",
                "TfNSW declared a response larger than the configured limit.",
            )

    @staticmethod
    def _read_bounded(endpoint: EndpointSpec, response: httpx.Response) -> bytes:
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > endpoint.max_bytes:
                raise DomainError(
                    "response_too_large",
                    "TfNSW returned more data than can be processed safely.",
                )
        return bytes(body)

    @staticmethod
    def _write_bounded(
        endpoint: EndpointSpec, response: httpx.Response, destination: Path
    ) -> None:
        total = 0
        with destination.open("wb") as output:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > endpoint.max_bytes:
                    raise DomainError(
                        "response_too_large",
                        "TfNSW returned more data than can be processed safely.",
                    )
                output.write(chunk)

    def _retry_delay(self, retry_state: object) -> float:
        attempt = int(getattr(retry_state, "attempt_number", 1))
        outcome = getattr(retry_state, "outcome", None)
        exception = outcome.exception() if outcome is not None else None
        if isinstance(exception, _RetryableStatus) and exception.retry_after:
            retry_after = exception.retry_after
            if retry_after.replace(".", "", 1).isdecimal():
                return min(float(retry_after), self._retry_policy.max_delay_seconds)
        exponential = self._retry_policy.base_delay_seconds * float(2 ** (attempt - 1))
        return float(min(exponential, self._retry_policy.max_delay_seconds))
