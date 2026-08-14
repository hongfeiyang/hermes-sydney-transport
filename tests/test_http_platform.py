from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from pydantic import ValidationError

from hermes_sydney_transport.adapters.tfnsw.codecs import JsonModelCodec
from hermes_sydney_transport.adapters.tfnsw.platform import (
    EndpointSpec,
    RetryPolicy,
    TfnswHttpClient,
)
from hermes_sydney_transport.adapters.tfnsw.wire.live_traffic import (
    FeatureCollectionWire,
)
from hermes_sydney_transport.adapters.tfnsw.wire.trip_planner import AlertsPayloadWire
from hermes_sydney_transport.models.errors import DomainError


def _endpoint(**changes: object) -> EndpointSpec:
    values: dict[str, object] = {
        "id": "test_endpoint",
        "url": "https://api.transport.nsw.gov.au/v1/test",
        "accept": "application/json",
        "content_types": frozenset({"application/json"}),
        "max_bytes": 1_024,
        "timeout_seconds": 5.0,
    }
    values.update(changes)
    return EndpointSpec.model_validate(values)


class TfnswHttpClientContractTests(unittest.TestCase):
    def _client(
        self,
        handler: httpx.MockTransport,
        *,
        attempts: int = 1,
        sleeper: object | None = None,
    ) -> TfnswHttpClient:
        raw_client = httpx.Client(transport=handler, follow_redirects=True)
        self.addCleanup(raw_client.close)
        options: dict[str, object] = {
            "retry_policy": RetryPolicy(
                max_attempts=attempts,
                base_delay_seconds=0.0,
                max_delay_seconds=1.0,
            ),
            "client": raw_client,
        }
        if sleeper is not None:
            options["sleeper"] = sleeper
        return TfnswHttpClient("secret-test-key", **options)  # type: ignore[arg-type]

    def test_sends_auth_and_conditional_headers(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "apikey secret-test-key")
            self.assertEqual(request.headers["If-Modified-Since"], "yesterday")
            self.assertEqual(request.headers["Accept"], "application/json")
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                content=b"{}",
            )

        payload = self._client(httpx.MockTransport(handler)).fetch(
            _endpoint(), if_modified_since="yesterday"
        )

        self.assertEqual(payload.body, b"{}")

    def test_rejects_redirect_without_replaying_secret(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://example.com/leak"})

        with self.assertRaises(DomainError) as caught:
            self._client(httpx.MockTransport(handler)).fetch(_endpoint())

        self.assertEqual(caught.exception.code, "upstream_http_error")
        self.assertEqual(len(requests), 1)
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_maps_authentication_failure_without_secret(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(401))

        with self.assertRaises(DomainError) as caught:
            self._client(transport).fetch(_endpoint())

        self.assertEqual(caught.exception.code, "authentication_failed")
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_retries_retryable_status_and_honours_bounded_retry_after(self) -> None:
        calls = 0
        delays: list[float] = []

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "0.5"})
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"{}",
            )

        payload = self._client(
            httpx.MockTransport(handler), attempts=2, sleeper=delays.append
        ).fetch(_endpoint())

        self.assertEqual(payload.body, b"{}")
        self.assertEqual(calls, 2)
        self.assertEqual(delays, [0.5])

    def test_maps_timeout_after_bounded_retries(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("deadline", request=request)

        with self.assertRaises(DomainError) as caught:
            self._client(httpx.MockTransport(handler), attempts=2).fetch(_endpoint())

        self.assertEqual(caught.exception.code, "upstream_unavailable")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(calls, 2)

    def test_accepts_allowed_not_modified_response(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(304))

        payload = self._client(transport).fetch(_endpoint(allow_not_modified=True))

        self.assertTrue(payload.not_modified)
        self.assertIsNone(payload.body)

    def test_rejects_unexpected_content_type(self) -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"Content-Type": "text/html"}, content=b"no"
            )
        )

        with self.assertRaises(DomainError) as caught:
            self._client(transport).fetch(_endpoint())

        self.assertEqual(caught.exception.code, "invalid_upstream_response")

    def test_rejects_declared_and_streamed_oversized_responses(self) -> None:
        declared = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "1025",
                },
                content=b"{}",
            )
        )
        streamed = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"x" * 1_025,
            )
        )

        for transport in (declared, streamed):
            with self.subTest(transport=transport):
                with self.assertRaises(DomainError) as caught:
                    self._client(transport).fetch(_endpoint())
                self.assertEqual(caught.exception.code, "response_too_large")

    def test_endpoint_spec_rejects_non_tfnsw_origin(self) -> None:
        for url in (
            "http://api.transport.nsw.gov.au/v1/test",
            "https://example.com/v1/test",
            "https://api.transport.nsw.gov.au@example.com/v1/test",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                _endpoint(url=url)

    def test_streaming_download_supports_public_unauthenticated_resources(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertNotIn("Authorization", request.headers)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/csv"},
                content=b"id,name\n1,Central\n",
            )

        endpoint = _endpoint(
            url="https://opendata.transport.nsw.gov.au/data/facilities.csv",
            accept="text/csv",
            content_types=frozenset({"text/csv"}),
            authenticated=False,
        )
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "facilities.csv"
            payload = self._client(httpx.MockTransport(handler)).download(
                endpoint, destination
            )
            self.assertEqual(destination.read_bytes(), b"id,name\n1,Central\n")
        self.assertIsNone(payload.body)
        self.assertFalse(payload.not_modified)

    def test_failed_download_removes_partial_destination(self) -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"x" * 1_025,
            )
        )
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "partial.bin"
            with self.assertRaises(DomainError) as caught:
                self._client(transport).download(_endpoint(), destination)
            self.assertFalse(destination.exists())
        self.assertEqual(caught.exception.code, "response_too_large")

    def test_not_modified_download_does_not_create_destination(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(304))
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "unchanged.zip"
            payload = self._client(transport).download(
                _endpoint(allow_not_modified=True), destination
            )
            self.assertFalse(destination.exists())
        self.assertTrue(payload.not_modified)


class JsonModelCodecContractTests(unittest.TestCase):
    def test_invalid_json_and_invalid_shape_share_one_safe_error(self) -> None:
        codec = JsonModelCodec(FeatureCollectionWire, source="fixture")

        for payload in (b"not-json", b'{"type":"FeatureCollection"}'):
            with (
                self.subTest(payload=payload),
                self.assertRaises(DomainError) as caught,
            ):
                codec.decode(payload)
            self.assertEqual(caught.exception.code, "invalid_upstream_response")
            self.assertNotIn(payload.decode(), str(caught.exception))

    def test_alert_affected_entities_enforce_the_250_item_wire_bound(self) -> None:
        codec = JsonModelCodec(AlertsPayloadWire, source="Trip Planner alerts")

        for field in ("lines", "stops"):
            with self.subTest(field=field):
                entities = [{"id": str(index)} for index in range(250)]
                payload = {"infos": {"current": [{"affected": {field: entities}}]}}
                decoded = codec(json.dumps(payload).encode())
                affected = getattr(decoded.infos.current[0].affected, field)
                self.assertEqual(len(affected), 250)

                payload["infos"]["current"][0]["affected"][field].append(
                    {"id": "overflow"}
                )
                with self.assertRaises(DomainError) as caught:
                    codec(json.dumps(payload).encode())
                self.assertEqual(
                    caught.exception.code,
                    "invalid_upstream_response",
                )


if __name__ == "__main__":
    unittest.main()
