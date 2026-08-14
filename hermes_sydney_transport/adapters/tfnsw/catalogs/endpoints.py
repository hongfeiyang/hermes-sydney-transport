"""Single source of allowlisted TfNSW endpoint policy."""

from __future__ import annotations

from types import MappingProxyType

from ..platform import EndpointSpec

_JSON_TYPES = frozenset({"application/json", "application/geo+json"})
_LIVE_BASE = "https://api.transport.nsw.gov.au/v1/live/hazards"

LIVE_TRAFFIC_ENDPOINTS = MappingProxyType(
    {
        hazard_type: EndpointSpec(
            id=f"live_traffic_{hazard_type}",
            url=f"{_LIVE_BASE}{path}",
            accept="application/json",
            content_types=_JSON_TYPES,
            max_bytes=8 * 1024 * 1024,
            timeout_seconds=15.0,
        )
        for hazard_type, path in {
            "incident": "/incident/open",
            "fire": "/fire/open",
            "flood": "/flood/open",
            "alpine": "/alpine/open",
            "major_event": "/majorevent/open",
            "roadwork": "/roadwork/open",
            "regional_lga_incident": "/regional-lga-incident/open",
        }.items()
    }
)

TRAFFIC_VOLUME_ENDPOINT = EndpointSpec(
    id="traffic_volume_counts",
    url="https://api.transport.nsw.gov.au/v1/traffic_volume",
    accept="application/json",
    content_types=_JSON_TYPES,
    max_bytes=8 * 1_024 * 1_024,
    timeout_seconds=15.0,
)

STATIC_RESOURCE_ENDPOINTS = MappingProxyType(
    {
        "complete_gtfs": EndpointSpec(
            id="complete_gtfs",
            url=(
                "https://api.transport.nsw.gov.au/v1/publictransport/"
                "timetables/complete/gtfs"
            ),
            accept="application/zip",
            content_types=frozenset({"application/octet-stream", "application/zip"}),
            max_bytes=384 * 1_024 * 1_024,
            timeout_seconds=180.0,
            allow_not_modified=True,
        ),
        "location_facilities": EndpointSpec(
            id="location_facilities",
            url=(
                "https://opendata.transport.nsw.gov.au/data/dataset/"
                "25f006fd-d0fb-4a8e-bfda-7ea4033c1aeb/resource/"
                "e9d94351-f22d-46ea-b64d-10e7e238368a/download/"
                "locationfacilitydata.csv"
            ),
            accept="text/csv",
            content_types=frozenset(
                {"application/csv", "application/octet-stream", "text/csv"}
            ),
            max_bytes=4 * 1_024 * 1_024,
            timeout_seconds=60.0,
            authenticated=False,
        ),
        "interchange_lifts": EndpointSpec(
            id="interchange_lifts",
            url=(
                "https://opendata.transport.nsw.gov.au/data/dataset/"
                "5ac00c2d-c5fb-48e1-b45a-b4d49be815f3/resource/"
                "c9b79c0f-4403-4f41-af0f-1fe8deaa6a33/download/"
                "interchange-facilities-lifts_may-2025.xlsx"
            ),
            accept=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            content_types=frozenset(
                {
                    "application/octet-stream",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }
            ),
            max_bytes=8 * 1_024 * 1_024,
            timeout_seconds=60.0,
            authenticated=False,
        ),
    }
)
