"""Validated model-facing inputs. JSON Schemas are generated from these models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
_DATETIME_ADAPTER = TypeAdapter(datetime)
_ISO_DATETIME_TEXT_ADAPTER: TypeAdapter[str] = TypeAdapter(
    Annotated[
        str,
        StringConstraints(
            max_length=40,
            pattern=(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
                r"(?::\d{2}(?:\.\d{1,6})?)?"
                r"(?:Z|[+-]\d{2}:\d{2})?$"
            ),
        ),
    ]
)


def _collapse_whitespace(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


StationQuery = Annotated[
    str,
    StringConstraints(min_length=2, max_length=100),
    BeforeValidator(_collapse_whitespace),
]
StopId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9:_-]+$"),
    BeforeValidator(_collapse_whitespace),
]
ServiceId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    BeforeValidator(_collapse_whitespace),
]
TripCode = Annotated[
    str,
    StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$"),
    BeforeValidator(_collapse_whitespace),
]
TransitMode = Literal["train", "bus"]


def _default_modes() -> list[TransitMode]:
    return ["train", "bus"]


class PluginInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class TimedInput(PluginInput):
    at: datetime | None = Field(
        default=None,
        description=(
            "Optional ISO 8601 date/time. A value without an offset is interpreted "
            "in Australia/Sydney. Defaults to now."
        ),
    )

    @field_validator("at", mode="before", json_schema_input_type=datetime | None)
    @classmethod
    def parse_iso_time(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        text = _ISO_DATETIME_TEXT_ADAPTER.validate_python(value, strict=True)
        return _DATETIME_ADAPTER.validate_python(text, strict=False)

    @field_validator("at")
    @classmethod
    def normalise_and_bound_time(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            candidates = [value.replace(tzinfo=SYDNEY_TZ, fold=fold) for fold in (0, 1)]
            valid = [
                candidate
                for candidate in candidates
                if candidate.astimezone(UTC).astimezone(SYDNEY_TZ).replace(tzinfo=None)
                == value
            ]
            if not valid:
                raise ValueError(
                    "is not a real Australia/Sydney local time because of the "
                    "daylight-saving transition"
                )
            if len({candidate.utcoffset() for candidate in valid}) > 1:
                raise ValueError(
                    "is ambiguous in Australia/Sydney; include an explicit UTC offset"
                )
            value = valid[0]
        value = value.astimezone(SYDNEY_TZ)
        context = info.context if isinstance(info.context, dict) else {}
        now = context.get("now") or datetime.now(SYDNEY_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=SYDNEY_TZ)
        now = now.astimezone(SYDNEY_TZ)
        if value < now - timedelta(days=1) or value > now + timedelta(days=14):
            raise ValueError(
                "must be no more than 1 day in the past or 14 days in the future"
            )
        return value


class ModeInput(PluginInput):
    modes: list[TransitMode] = Field(
        default_factory=_default_modes,
        min_length=1,
        max_length=2,
        description="Transport modes to include. Supported values are train and bus.",
    )

    @field_validator("modes")
    @classmethod
    def modes_are_unique(cls, value: list[TransitMode]) -> list[TransitMode]:
        if len(set(value)) != len(value):
            raise ValueError("modes must not contain duplicates")
        return value


class StationSearchInput(ModeInput):
    query: StationQuery = Field(
        description="Station name or partial name, such as Central or Parramatta."
    )
    limit: StrictInt = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum matching stations to return.",
    )


class NearbyStopsInput(PluginInput):
    latitude: float = Field(
        ge=-90,
        le=90,
        allow_inf_nan=False,
        description="Latitude in WGS84/EPSG:4326.",
    )
    longitude: float = Field(
        ge=-180,
        le=180,
        allow_inf_nan=False,
        description="Longitude in WGS84/EPSG:4326.",
    )
    radius_metres: StrictInt = Field(
        default=1000,
        ge=100,
        le=5000,
        description="Search radius in metres.",
    )
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum deduplicated stops to return.",
    )


class DeparturesInput(TimedInput, ModeInput):
    stop_id: StopId = Field(
        description="Stop ID returned by sydney_transport_search_stops."
    )
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum departures to return.",
    )


class TripPlanInput(TimedInput, ModeInput):
    origin_stop_id: StopId = Field(description="Origin TfNSW stop ID.")
    destination_stop_id: StopId = Field(description="Destination TfNSW stop ID.")
    time_mode: Literal["depart", "arrive"] = Field(
        default="depart",
        description=(
            "Use depart for journeys leaving at/after the time or arrive for "
            "journeys arriving at/before it."
        ),
    )
    wheelchair: StrictBool = Field(
        default=False,
        description="When true, request wheelchair-accessible options only.",
    )
    limit: StrictInt = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum journey options to return.",
    )

    @model_validator(mode="after")
    def stops_must_differ(self) -> TripPlanInput:
        if self.origin_stop_id == self.destination_stop_id:
            raise ValueError("origin_stop_id and destination_stop_id must differ")
        return self


class AlertsInput(ModeInput):
    stop_id: StopId | None = Field(
        default=None,
        description=(
            "Optional station/stop ID from sydney_transport_search_stops. "
            "Omit for current alerts across the requested modes."
        ),
    )
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum alerts to return, highest priority first.",
    )


class RealtimeServiceInput(TimedInput):
    service_id: ServiceId | None = Field(
        default=None,
        description=(
            "Preferred exact GTFS-Realtime service ID returned as service_id by "
            "sydney_transport_departures. Omit trip_code and stop_id when using it."
        ),
    )
    trip_code: TripCode | None = Field(
        default=None,
        description=(
            "Fallback Trip Planner trip code returned by sydney_transport_departures. "
            "Requires stop_id; provide at when resolving a past or ambiguous departure."
        ),
    )
    stop_id: StopId | None = Field(
        default=None,
        description=(
            "Departure stop ID used to resolve trip_code to an exact realtime service. "
            "Omit when service_id is supplied."
        ),
    )

    @model_validator(mode="after")
    def has_one_service_reference(self) -> RealtimeServiceInput:
        if (self.service_id is None) == (self.trip_code is None):
            raise ValueError("provide exactly one of service_id or trip_code")
        if self.trip_code is not None and self.stop_id is None:
            raise ValueError("stop_id is required when trip_code is used")
        if self.service_id is not None and self.stop_id is not None:
            raise ValueError("stop_id must be omitted when service_id is used")
        return self


class ServiceStatusInput(RealtimeServiceInput):
    """Resolve one train and return its current stop-by-stop service state."""


class VehiclePositionInput(RealtimeServiceInput):
    """Resolve one train and return its latest reported physical position."""


class BusServiceStatusInput(RealtimeServiceInput):
    """Resolve one bus and return its current stop-by-stop service state."""


class BusVehiclePositionInput(RealtimeServiceInput):
    """Resolve one bus and return its latest reported physical position."""
