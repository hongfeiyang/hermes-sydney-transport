"""Validated normalized outputs and stable tool envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

_DATETIME_ADAPTER = TypeAdapter(datetime)
_TIMESTAMP_TEXT_ADAPTER: TypeAdapter[str] = TypeAdapter(
    Annotated[
        str,
        StringConstraints(
            max_length=40,
            pattern=(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
                r"(?::\d{2}(?:\.\d{1,6})?)?"
                r"(?:Z|[+-]\d{2}:\d{2})$"
            ),
        ),
    ]
)


def _parse_timestamp(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        # Pydantic intentionally lets TypeError escape validators; ValueError keeps
        # upstream type drift inside the normal ValidationError contract.
        raise ValueError("must be an ISO 8601 date/time string")  # noqa: TRY004
    text = _TIMESTAMP_TEXT_ADAPTER.validate_python(value, strict=True)
    return _DATETIME_ADAPTER.validate_python(text, strict=False)


Timestamp = Annotated[AwareDatetime, BeforeValidator(_parse_timestamp)]


class PluginOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResultMetadata(PluginOutput):
    fetched_at: Timestamp
    source: str
    attribution: str


class Coordinates(PluginOutput):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Station(PluginOutput):
    id: str
    name: str
    short_name: str | None
    parent_name: str | None
    modes: list[int]
    match_quality: int
    is_best: bool
    coordinates: Coordinates | None


PublicTransitMode = Literal["train", "bus", "metro", "light_rail", "ferry"]


class StationSearchResult(ResultMetadata):
    query: str
    requested_modes: list[PublicTransitMode]
    stations: list[Station]
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def count_matches_stations(self) -> StationSearchResult:
        if self.count != len(self.stations):
            raise ValueError("count must equal the number of stations")
        return self


class NearbyQuery(PluginOutput):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_metres: int = Field(ge=100, le=5000)


class NearbyStop(PluginOutput):
    id: str
    name: str
    distance_metres: int | None = Field(ge=0)
    coordinates: Coordinates | None
    location_types: list[str]
    platforms: list[str]
    platform_count: int = Field(ge=0)

    @model_validator(mode="after")
    def count_matches_platforms(self) -> NearbyStop:
        if self.platform_count != len(self.platforms):
            raise ValueError("platform_count must equal the number of platforms")
        return self


class NearbyStopsResult(ResultMetadata):
    query: NearbyQuery
    stops: list[NearbyStop]
    count: int = Field(ge=0)
    mode_note: str

    @model_validator(mode="after")
    def count_matches_stops(self) -> NearbyStopsResult:
        if self.count != len(self.stops):
            raise ValueError("count must equal the number of stops")
        return self


class Route(PluginOutput):
    id: str | None
    number: str | None
    name: str | None
    icon_id: int | None
    product_class: int | None


class Departure(PluginOutput):
    mode: PublicTransitMode
    planned_time: Timestamp | None
    estimated_time: Timestamp | None
    status: Literal["cancelled", "unknown", "delayed", "early", "on_time"]
    delay_minutes: int | None
    realtime_available: bool
    cancelled: bool | None
    platform: str | None
    route: Route
    destination: str | None
    operator: str | None
    trip_code: str | None
    service_id: str | None
    alert_ids: list[str]


class DeparturesResult(ResultMetadata):
    stop_id: str
    requested_modes: list[PublicTransitMode]
    station: Station | None
    requested_at: Timestamp
    departures: list[Departure]
    count: int = Field(ge=0)
    realtime_note: str

    @model_validator(mode="after")
    def count_matches_departures(self) -> DeparturesResult:
        if self.count != len(self.departures):
            raise ValueError("count must equal the number of departures")
        return self


class TripStop(PluginOutput):
    id: str | None
    name: str | None
    short_name: str | None
    parent_id: str | None
    platform: str | None
    departure_time_planned: Timestamp | None
    departure_time_estimated: Timestamp | None
    arrival_time_planned: Timestamp | None
    arrival_time_estimated: Timestamp | None
    wheelchair_accessible: bool | None
    coordinates: Coordinates | None


class TripRoute(PluginOutput):
    id: str | None
    number: str | None
    name: str | None
    description: str | None
    product_class: int | None


class TripLeg(PluginOutput):
    mode: str
    duration_seconds: int | None = Field(ge=0)
    duration_minutes: int | None = Field(ge=0)
    distance_metres: int | None = Field(ge=0)
    is_realtime_controlled: bool | None
    realtime_status: str | None
    cancelled: bool | None
    origin: TripStop
    destination: TripStop
    route: TripRoute
    operator: str | None
    service_destination: str | None
    stop_count: int = Field(ge=0)
    stops: list[TripStop]
    alert_ids: list[str]
    hints: list[str]

    @model_validator(mode="after")
    def count_matches_stops(self) -> TripLeg:
        if self.stop_count != len(self.stops):
            raise ValueError("stop_count must equal the number of returned stops")
        return self


class Journey(PluginOutput):
    departure_time_planned: Timestamp | None
    departure_time_estimated: Timestamp | None
    arrival_time_planned: Timestamp | None
    arrival_time_estimated: Timestamp | None
    duration_seconds: int | None = Field(ge=0)
    duration_minutes: int | None = Field(ge=0)
    interchanges: int = Field(ge=0)
    realtime_available: bool | None
    cancelled: bool | None
    rating: int | None
    alert_ids: list[str]
    legs: list[TripLeg]


class SystemMessage(PluginOutput):
    type: str | None
    code: int | None
    message: str
    module: str | None


class TripPlanResult(ResultMetadata):
    origin_stop_id: str
    destination_stop_id: str
    requested_at: Timestamp
    time_mode: Literal["depart", "arrive"]
    wheelchair_requested: bool
    requested_modes: list[PublicTransitMode]
    journeys: list[Journey]
    count: int = Field(ge=0)
    system_messages: list[SystemMessage]
    mode_note: str

    @model_validator(mode="after")
    def count_matches_journeys(self) -> TripPlanResult:
        if self.count != len(self.journeys):
            raise ValueError("count must equal the number of journeys")
        return self


class AffectedEntity(PluginOutput):
    id: str | None
    name: str | None
    number: str | None


class TimeRange(PluginOutput):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    from_: Timestamp | None = Field(alias="from")
    to: Timestamp | None


class Alert(PluginOutput):
    id: str | None
    version: int | None
    priority: str
    type: str | None
    title: str
    content: str
    sms_summary: str
    affected_lines: list[AffectedEntity]
    affected_stops: list[AffectedEntity]
    created_at: Timestamp | None
    last_modified: Timestamp | None
    validity: list[TimeRange]
    availability: list[TimeRange]
    provider: str | None
    source_name: str | None
    url: str | None
    url_text: str


class AlertScope(PluginOutput):
    stop_id: str | None = None
    network: str | None = None

    @model_validator(mode="after")
    def has_exactly_one_scope(self) -> AlertScope:
        if (self.stop_id is None) == (self.network is None):
            raise ValueError("exactly one of stop_id or network must be set")
        return self


class AlertsResult(ResultMetadata):
    scope: AlertScope
    requested_modes: list[PublicTransitMode]
    alerts: list[Alert]
    count: int = Field(ge=0)
    remote_content_is_untrusted: Literal[True]

    @model_validator(mode="after")
    def count_matches_alerts(self) -> AlertsResult:
        if self.count != len(self.alerts):
            raise ValueError("count must equal the number of alerts")
        return self


RealtimeMode = Literal["train", "bus", "metro", "light_rail", "ferry"]


class RealtimeQuery(PluginOutput):
    mode: RealtimeMode
    requested_service_id: str | None
    trip_code: str | None
    stop_id: str | None
    requested_at: Timestamp | None
    resolved_service_id: str
    resolution: Literal["service_id", "trip_code"]


class Confidence(PluginOutput):
    level: Literal["high", "medium", "low", "none"]
    reasons: list[str]


class RealtimeDataQuality(PluginOutput):
    feed_age_seconds: int = Field(ge=0)
    observation_age_seconds: int | None = Field(default=None, ge=0)
    feed_is_stale: bool
    realtime_entity_present: bool
    static_join_successful: bool
    used_prediction: bool
    used_inference: bool
    warnings: list[str]


class ServiceDescription(PluginOutput):
    mode: RealtimeMode
    service_id: str
    route_id: str | None
    agency_id: str | None
    route_type: int | None
    route_short_name: str | None
    route_long_name: str | None
    headsign: str | None
    start_date: str | None
    start_time: str | None
    schedule_relationship: Literal[
        "scheduled", "added", "unscheduled", "cancelled", "replacement", "unknown"
    ]


class RealtimeStop(PluginOutput):
    id: str
    name: str | None
    parent_station_id: str | None
    parent_station_name: str | None
    platform: str | None


class StopPrediction(PluginOutput):
    sequence: int | None = Field(ge=0)
    planned_stop: RealtimeStop | None
    current_stop: RealtimeStop
    arrival_planned: Timestamp | None
    arrival_predicted: Timestamp | None
    departure_planned: Timestamp | None
    departure_predicted: Timestamp | None
    prediction_source: Literal[
        "absolute_time", "stop_delay", "trip_delay", "schedule", "unavailable"
    ]
    schedule_relationship: Literal["scheduled", "skipped", "no_data", "unscheduled"]
    skipped: bool
    stop_changed: bool


class StopChange(PluginOutput):
    sequence: int | None = Field(ge=0)
    location_name: str | None
    change_type: Literal["platform", "stop"]
    planned_stop: RealtimeStop
    current_stop: RealtimeStop


class ServiceStatusResult(ResultMetadata):
    query: RealtimeQuery
    feed_timestamp: Timestamp
    observation_timestamp: Timestamp
    service: ServiceDescription
    state: Literal["scheduled", "in_progress", "completed", "cancelled", "unknown"]
    is_cancelled: bool
    cancellation_source: Literal["none", "trip_update", "trip_update_and_bundle"]
    next_stop: StopPrediction | None
    last_passed_stop: StopPrediction | None
    stop_updates: list[StopPrediction]
    stop_count: int = Field(ge=0)
    skipped_stops: list[RealtimeStop]
    stop_changes: list[StopChange]
    confidence: Confidence
    data_quality: RealtimeDataQuality
    coverage_note: str

    @model_validator(mode="after")
    def count_matches_stop_updates(self) -> ServiceStatusResult:
        if self.stop_count != len(self.stop_updates):
            raise ValueError("stop_count must equal the number of stop updates")
        if self.is_cancelled != (self.state == "cancelled"):
            raise ValueError("is_cancelled must agree with service state")
        if self.is_cancelled != (self.cancellation_source != "none"):
            raise ValueError("cancellation_source must agree with cancellation state")
        return self


OccupancyLevel = Literal[
    "empty",
    "many_seats_available",
    "few_seats_available",
    "standing_room_only",
    "crushed_standing_room_only",
    "full",
    "not_accepting_passengers",
    "unknown",
]


class CarriageOccupancy(PluginOutput):
    name: str | None
    position_in_consist: int = Field(ge=1)
    occupancy: OccupancyLevel | None
    quiet_carriage: bool | None
    toilet: Literal["none", "normal", "accessible", "unknown"] | None
    luggage_rack: bool | None


class OccupancyReport(PluginOutput):
    reported: bool
    level: OccupancyLevel | None
    source: Literal["none", "vehicle", "carriage", "vehicle_and_carriage"]
    carriages: list[CarriageOccupancy]
    coverage_note: str

    @model_validator(mode="after")
    def source_matches_reported_data(self) -> OccupancyReport:
        if self.reported != (self.source != "none"):
            raise ValueError("reported must agree with occupancy source")
        if "vehicle" in self.source and self.level is None:
            raise ValueError("vehicle occupancy source requires a whole-train level")
        if "carriage" in self.source and not self.carriages:
            raise ValueError("carriage occupancy source requires carriage data")
        if self.source == "none" and (self.level is not None or self.carriages):
            raise ValueError("unreported occupancy cannot contain occupancy data")
        return self


class VehicleDetails(PluginOutput):
    label: str | None
    model: str | None
    air_conditioned: bool | None
    wheelchair_accessible: bool | None


class PositionReport(PluginOutput):
    coordinates: Coordinates
    bearing_degrees: float | None = Field(default=None, ge=0, le=360)
    speed_metres_per_second: float | None = Field(default=None, ge=0)
    track_direction: Literal["up", "down", "unknown"]
    reported_at: Timestamp


class VehicleStopContext(PluginOutput):
    """Explicit versus statically inferred stop context for a vehicle entity."""

    at_stop: RealtimeStop | None
    last_passed_stop: RealtimeStop | None
    target_stop: RealtimeStop | None
    inferred: bool


class VehiclePositionResult(ResultMetadata):
    query: RealtimeQuery
    feed_timestamp: Timestamp
    service: ServiceDescription
    available: bool
    vehicle: VehicleDetails | None
    position: PositionReport | None
    current_status: Literal["incoming_at", "stopped_at", "in_transit_to", "unknown"]
    stop_context: VehicleStopContext
    occupancy: OccupancyReport
    confidence: Confidence
    data_quality: RealtimeDataQuality
    coverage_note: str

    @model_validator(mode="after")
    def availability_matches_position(self) -> VehiclePositionResult:
        if self.available != (self.position is not None):
            raise ValueError("available must agree with reported position")
        if self.position is not None and self.vehicle is None:
            raise ValueError("a reported position requires vehicle details")
        return self


class ToolError(PluginOutput):
    code: str
    message: str
    retryable: bool
    http_status: int | None = None
    details: list[dict[str, Any]] | None = None


class SuccessEnvelope(PluginOutput):
    ok: Literal[True] = True
    data: dict[str, Any]


class ErrorEnvelope(PluginOutput):
    ok: Literal[False] = False
    error: ToolError
