"""Stop accessibility policy over static facilities and current alerts."""

from __future__ import annotations

from typing import Literal

from ..models.metadata import ATTRIBUTION
from ..models.outputs import Coordinates
from ..models.static_inputs import StopAccessibilityInput
from ..models.static_outputs import (
    AccessibilityWarning,
    StaticFacility,
    StaticLift,
    StopAccessibilityResult,
)
from ..ports.alerts import AlertQuery, AlertRecord, AlertsPort
from ..ports.clock import Clock
from ..ports.facilities import FacilitiesPort, FacilityRecord, LiftRecord
from ..ports.realtime import TransportMode

_SOURCE = "TfNSW Location Facilities, Interchange Facilities, and Alerts v2"
_ALL_MODES = tuple(TransportMode)
_STATIC_LIMITATION = (
    "Facilities and lifts are static inventory only. Lift inventory approval or "
    "presence is not evidence that a lift is currently operating."
)
_WARNING_LIMITATION = (
    "Current status is inferred only from published accessibility alerts for the "
    "exact stop ID. No matching warning does not prove every facility is operating."
)


class GetStopAccessibility:
    def __init__(
        self,
        facilities: FacilitiesPort,
        alerts: AlertsPort,
        clock: Clock,
    ) -> None:
        self._facilities = facilities
        self._alerts = alerts
        self._clock = clock

    def execute(self, request: StopAccessibilityInput) -> StopAccessibilityResult:
        now = self._clock.now()
        snapshot = self._facilities.get_facility(request.stop_id)
        warnings: tuple[AlertRecord, ...] = ()
        warning_status: Literal[
            "warnings_reported", "none_reported", "not_requested", "unavailable"
        ] = "not_requested"
        warnings_checked = False
        warning_unavailable = False
        if request.include_current_warnings:
            warnings_checked = True
            outcome = self._alerts.query_alerts(
                AlertQuery(
                    modes=_ALL_MODES,
                    stop_id=request.stop_id,
                    route_id=None,
                    trip_id=None,
                    causes=(),
                    effects=("accessibility_issue",),
                    active_at=now,
                )
            )
            if outcome.is_available:
                warnings = outcome.value or ()
                warning_status = "warnings_reported" if warnings else "none_reported"
            else:
                warning_status = "unavailable"
                warning_unavailable = True
        limitations = [_STATIC_LIMITATION, _WARNING_LIMITATION]
        if snapshot.facility is None:
            limitations.append(
                "No exact EFA_ID or TSN match was found in the facilities dataset."
            )
        if snapshot.cache_stale:
            limitations.append(
                "The latest static refresh failed, so the last valid cache was used."
            )
        if warning_unavailable:
            limitations.append(
                "Current accessibility alerts were unavailable; static inventory is "
                "still returned without a current-status claim."
            )
        ordered = sorted(warnings, key=lambda item: item.id)[: request.warning_limit]
        warning_outputs = [_warning_output(item) for item in ordered]
        return StopAccessibilityResult(
            fetched_at=now,
            source=_SOURCE,
            attribution=ATTRIBUTION,
            stop_id=request.stop_id,
            matched_by=snapshot.matched_by,
            facility=_facility_output(snapshot.facility),
            lifts=[_lift_output(lift) for lift in snapshot.lifts],
            lift_count=len(snapshot.lifts),
            current_warnings_checked=warnings_checked,
            current_warnings=warning_outputs,
            current_warning_count=len(warning_outputs),
            current_warning_status=warning_status,
            operational_status="disruption_reported" if ordered else "unknown",
            static_source_updated_at=snapshot.source_updated_at,
            static_cache_stale=snapshot.cache_stale,
            limitations=limitations,
            remote_content_is_untrusted=True,
        )


def _facility_output(item: FacilityRecord | None) -> StaticFacility | None:
    if item is None:
        return None
    coordinates = (
        Coordinates.model_validate(item.coordinates, from_attributes=True)
        if item.coordinates is not None
        else None
    )
    return StaticFacility(
        name=item.name,
        efa_id=item.efa_id,
        tsn=item.tsn,
        address=item.address,
        phone=item.phone,
        coordinates=coordinates,
        transport_modes=list(item.transport_modes),
        accessibility_classification=item.accessibility_classification,
        accessibility_features=list(item.accessibility_features),
        facilities=list(item.facilities),
        morning_staffed_hours=item.morning_staffed_hours,
        afternoon_staffed_hours=item.afternoon_staffed_hours,
        short_platform=item.short_platform,
    )


def _lift_output(item: LiftRecord) -> StaticLift:
    return StaticLift(
        functional_location_code=item.functional_location_code,
        description=item.description,
        inventory_record_updated_at=item.inventory_record_updated_at,
        operational_status="unknown",
    )


def _warning_output(item: AlertRecord) -> AccessibilityWarning:
    starts = [
        period.start for period in item.active_periods if period.start is not None
    ]
    ends = [period.end for period in item.active_periods if period.end is not None]
    return AccessibilityWarning(
        id=item.id,
        title=item.title,
        description=item.description,
        active_from=min(starts) if starts else None,
        active_until=max(ends) if ends else None,
        severity=item.severity,
        effect="accessibility_issue",
    )
