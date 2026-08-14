from __future__ import annotations

import json
import unittest
from datetime import UTC

from hermes_sydney_transport.adapters.tfnsw.codecs import JsonModelCodec
from hermes_sydney_transport.adapters.tfnsw.wire.base import WireModel
from hermes_sydney_transport.adapters.tfnsw.wire.timestamps import (
    NullableTimestamp,
    OptionalProviderTimestamp,
    WireTimestamp,
)
from hermes_sydney_transport.models.errors import DomainError


class TimestampEnvelope(WireModel):
    required: WireTimestamp
    nullable: NullableTimestamp = None
    provider_timestamp: OptionalProviderTimestamp = None


class WireTimestampContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = JsonModelCodec(TimestampEnvelope, source="timestamp fixture")

    def test_shared_contract_normalises_every_supported_provider_shape(self) -> None:
        result = self.codec(
            json.dumps(
                {
                    "required": "2026-08-12T09:00:00+10:00",
                    "nullable": "2026-08-16 22:00:00 UTC",
                    "provider_timestamp": 1_786_500_000_000,
                }
            ).encode()
        )

        self.assertEqual(result.required.utcoffset().total_seconds(), 10 * 60 * 60)
        self.assertEqual(result.nullable.tzinfo, UTC)
        self.assertEqual(result.provider_timestamp.tzinfo, UTC)

    def test_null_vocabulary_is_centralized(self) -> None:
        for null_value in (None, "", "NULL"):
            with self.subTest(null_value=null_value):
                result = self.codec(
                    json.dumps(
                        {
                            "required": "2026-08-12T00:00:00Z",
                            "nullable": null_value,
                            "provider_timestamp": 0,
                        }
                    ).encode()
                )
                self.assertIsNone(result.nullable)
                self.assertIsNone(result.provider_timestamp)

    def test_invalid_timestamp_shapes_share_the_canonical_codec_error(self) -> None:
        invalid_values = (
            "2026-08-12T09:00:00",
            "2026-08-12",
            "1786500000",
            1_786_500_000,
            1.5,
            True,
        )
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(DomainError) as caught:
                    self.codec(
                        json.dumps(
                            {
                                "required": invalid,
                                "provider_timestamp": 1_786_500_000_000,
                            }
                        ).encode()
                    )
                self.assertEqual(caught.exception.code, "invalid_upstream_response")

    def test_epoch_milliseconds_reject_other_numeric_encodings(self) -> None:
        for invalid in (-1, 4_102_444_800_001, 1.5, True, "1786500000000"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(DomainError) as caught:
                    self.codec(
                        json.dumps(
                            {
                                "required": "2026-08-12T00:00:00Z",
                                "provider_timestamp": invalid,
                            }
                        ).encode()
                    )
                self.assertEqual(caught.exception.code, "invalid_upstream_response")


if __name__ == "__main__":
    unittest.main()
