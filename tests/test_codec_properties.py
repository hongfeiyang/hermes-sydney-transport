from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from hermes_sydney_transport.adapters.tfnsw.codecs import JsonModelCodec
from hermes_sydney_transport.adapters.tfnsw.platform import EndpointSpec
from hermes_sydney_transport.adapters.tfnsw.wire.facilities import FacilityCsvRow
from hermes_sydney_transport.adapters.tfnsw.wire.gtfs import StopTimeRow
from hermes_sydney_transport.adapters.tfnsw.wire.live_traffic import (
    FeatureCollectionWire,
)
from hermes_sydney_transport.models.errors import DomainError

_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=40),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
)


class CodecPropertyTests(unittest.TestCase):
    @settings(max_examples=100, deadline=None)
    @given(st.binary(max_size=512))
    def test_json_codec_always_returns_a_model_or_one_canonical_error(
        self, payload: bytes
    ) -> None:
        codec = JsonModelCodec(FeatureCollectionWire, source="property fixture")
        try:
            result = codec.decode(payload)
        except DomainError as exc:
            self.assertEqual(exc.code, "invalid_upstream_response")
        else:
            self.assertIsInstance(result, FeatureCollectionWire)

    @settings(max_examples=150, deadline=None)
    @given(st.dictionaries(st.text(max_size=30), _SCALAR, max_size=20))
    def test_facility_wire_never_leaks_parser_exceptions(
        self, value: dict[str, object]
    ) -> None:
        try:
            FacilityCsvRow.model_validate(value)
        except ValidationError:
            pass

    @settings(max_examples=150, deadline=None)
    @given(st.dictionaries(st.text(max_size=30), _SCALAR, max_size=20))
    def test_gtfs_wire_never_leaks_parser_exceptions(
        self, value: dict[str, object]
    ) -> None:
        try:
            StopTimeRow.model_validate(value)
        except ValidationError:
            pass

    @settings(max_examples=100, deadline=None)
    @given(st.text(max_size=300))
    def test_endpoint_acceptance_implies_an_exact_tfnsw_origin(self, url: str) -> None:
        try:
            endpoint = EndpointSpec(
                id="property_endpoint",
                url=url,
                accept="application/json",
                content_types=frozenset({"application/json"}),
                max_bytes=1_024,
                timeout_seconds=1.0,
                authenticated=False,
            )
        except ValidationError:
            return
        self.assertTrue(
            endpoint.url == "https://api.transport.nsw.gov.au"
            or endpoint.url.startswith("https://api.transport.nsw.gov.au/")
            or endpoint.url == "https://opendata.transport.nsw.gov.au"
            or endpoint.url.startswith("https://opendata.transport.nsw.gov.au/")
        )
        self.assertNotIn("#", endpoint.url)


if __name__ == "__main__":
    unittest.main()
