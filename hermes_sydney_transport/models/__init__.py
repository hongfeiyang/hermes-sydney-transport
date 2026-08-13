"""Pydantic input and output contracts for the plugin."""

from .inputs import (
    AlertsInput,
    DeparturesInput,
    NearbyStopsInput,
    StationSearchInput,
    TripPlanInput,
)
from .outputs import (
    AlertsResult,
    DeparturesResult,
    ErrorEnvelope,
    NearbyStopsResult,
    StationSearchResult,
    SuccessEnvelope,
    TripPlanResult,
)

__all__ = [
    "AlertsInput",
    "AlertsResult",
    "DeparturesInput",
    "DeparturesResult",
    "ErrorEnvelope",
    "NearbyStopsInput",
    "NearbyStopsResult",
    "StationSearchInput",
    "StationSearchResult",
    "SuccessEnvelope",
    "TripPlanInput",
    "TripPlanResult",
]
