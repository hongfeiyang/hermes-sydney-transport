from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from hermes_sydney_transport.adapters.tfnsw.binary_transport import (
    UrllibBinaryTransport,
)
from hermes_sydney_transport.models.errors import DomainError as TfnswApiError


class FakeResponse:
    def __init__(self, body: bytes, headers=None):
        self.body = body
        self.headers = headers or {
            "Content-Type": "application/x-google-protobuf",
            "Last-Modified": "Wed, 12 Aug 2026 08:00:00 GMT",
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return self.body[:limit]


class BinaryTransportTests(unittest.TestCase):
    def test_fetches_only_allowlisted_feed_and_keeps_key_in_header(self):
        transport = UrllibBinaryTransport("test-key")
        with patch.object(
            transport._opener, "open", return_value=FakeResponse(b"protobuf")
        ) as mocked_open:
            result = transport.get("trip_updates")

        self.assertEqual(result.data, b"protobuf")
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "apikey test-key")
        self.assertEqual(
            request.full_url,
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains",
        )
        with self.assertRaises(ValueError):
            transport.get("arbitrary")

    def test_redirect_is_rejected_and_response_is_closed(self):
        transport = UrllibBinaryTransport("test-key")
        redirect = HTTPError(
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains",
            302,
            "Found",
            {"Location": "https://attacker.invalid/collect"},
            BytesIO(),
        )
        with (
            patch.object(transport._opener, "open", side_effect=redirect),
            self.assertRaises(TfnswApiError) as raised,
        ):
            transport.get("trip_updates")
        self.assertEqual(raised.exception.http_status, 302)
        self.assertTrue(redirect.closed)

    def test_conditional_static_request_accepts_not_modified(self):
        transport = UrllibBinaryTransport("test-key")
        not_modified = HTTPError(
            "https://api.transport.nsw.gov.au/v1/gtfs/schedule/sydneytrains",
            304,
            "Not Modified",
            {"Last-Modified": "Wed, 12 Aug 2026 08:00:00 GMT"},
            BytesIO(),
        )
        with patch.object(transport._opener, "open", side_effect=not_modified):
            result = transport.get(
                "static_schedule",
                if_modified_since="Wed, 12 Aug 2026 08:00:00 GMT",
            )
        self.assertTrue(result.not_modified)
        self.assertIsNone(result.data)
        self.assertTrue(not_modified.closed)

    def test_multi_feed_mode_uses_get_all_and_correct_first_url(self):
        transport = UrllibBinaryTransport("test-key", mode="light_rail")
        with patch.object(
            transport._opener, "open", return_value=FakeResponse(b"protobuf")
        ) as mocked_open:
            result = transport.get_all("trip_updates")

        self.assertEqual(len(result), 4)
        first_request = mocked_open.call_args_list[0].args[0]
        self.assertEqual(
            first_request.full_url,
            "https://api.transport.nsw.gov.au/v2/gtfs/realtime/lightrail/innerwest",
        )


if __name__ == "__main__":
    unittest.main()
