"""Canonical outputs for static accessibility and Complete GTFS schedules."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .outputs import Coordinates, PluginOutput, ResultMetadata, Timestamp


class StaticFacility(PluginOutput):
    name: str
    efa_id: str
    tsn: str
    address: str | None
    phone: str | None
    coordinates: Coordinates | None
    transport_modes: list[str]
    accessibility_classification: Literal[
        "independent_access", "assisted_access", "not_accessible", "unknown"
    ]
    accessibility_features: list[str]
    facilities: list[str]
    morning_staffed_hours: str | None
    afternoon_staffed_hours: str | None
    short_platform: bool | None


class StaticLift(PluginOutput):
    functional_location_code: str | None
    description: str | None
    inventory_record_updated_at: Timestamp | None
    operational_status: Literal["unknown"]


class AccessibilityWarning(PluginOutput):
    id: str
    title: str
    description: str
    active_from: Timestamp | None
    active_until: Timestamp | None
    severity: str | None
    effect: Literal["accessibility_issue"]


class StopAccessibilityResult(ResultMetadata):
    stop_id: str
    matched_by: Literal["efa_id", "tsn", "none"]
    facility: StaticFacility | None
    lifts: list[StaticLift]
    lift_count: int = Field(ge=0)
    current_warnings_checked: bool
    current_warnings: list[AccessibilityWarning]
    current_warning_count: int = Field(ge=0)
    current_warning_status: Literal[
        "warnings_reported", "none_reported", "not_requested", "unavailable"
    ]
    operational_status: Literal["disruption_reported", "unknown"]
    static_source_updated_at: Timestamp | None
    static_cache_stale: bool
    limitations: list[str]
    remote_content_is_untrusted: Literal[True]

    @model_validator(mode="after")
    def counts_match_items(self) -> StopAccessibilityResult:
        if self.lift_count != len(self.lifts):
            raise ValueError("lift_count must equal the number of lifts")
        if self.current_warning_count != len(self.current_warnings):
            raise ValueError(
                "current_warning_count must equal the number of current warnings"
            )
        if self.matched_by == "none" and self.facility is not None:
            raise ValueError("facility must be absent when matched_by is none")
        if self.matched_by != "none" and self.facility is None:
            raise ValueError("facility is required for a successful static match")
        return self


class TimetableRoute(PluginOutput):
    id: str
    agency_id: str | None
    short_name: str | None
    long_name: str | None
    description: str | None
    route_type: int | None


class ScheduledStopTime(PluginOutput):
    stop_id: str
    stop_name: str | None
    sequence: int = Field(ge=0)
    arrival: Timestamp | None
    departure: Timestamp | None
    pickup_type: int | None = Field(default=None, ge=0, le=3)
    drop_off_type: int | None = Field(default=None, ge=0, le=3)


class ScheduledTrip(PluginOutput):
    complete_gtfs_trip_id: str
    headsign: str | None
    direction_id: Literal[0, 1] | None
    wheelchair_accessibility: Literal["accessible", "not_accessible", "unknown"]
    first_departure: Timestamp | None
    last_arrival: Timestamp | None
    stop_times: list[ScheduledStopTime]
    stop_count: int = Field(ge=0)
    stop_times_truncated: bool

    @model_validator(mode="after")
    def count_matches_stops(self) -> ScheduledTrip:
        if self.stop_count != len(self.stop_times):
            raise ValueError("stop_count must equal the returned stop times")
        return self


class RouteTimetableResult(ResultMetadata):
    identifier_namespace: Literal["complete_gtfs"]
    identifiers_match_realtime_feeds: Literal[False]
    route: TimetableRoute
    service_date: date
    direction_id: Literal[0, 1] | None
    stop_id: str | None
    trips: list[ScheduledTrip]
    count: int = Field(ge=0)
    static_source_updated_at: Timestamp | None
    static_cache_stale: bool
    limitations: list[str]

    @model_validator(mode="after")
    def count_matches_trips(self) -> RouteTimetableResult:
        if self.count != len(self.trips):
            raise ValueError("count must equal the number of trips")
        return self
