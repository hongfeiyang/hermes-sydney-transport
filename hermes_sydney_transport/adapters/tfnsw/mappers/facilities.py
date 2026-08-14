"""Pure projection from persisted facility records to semantic port records."""

from __future__ import annotations

from ....ports.facilities import (
    AccessibilityClassification,
    FacilityCoordinates,
    FacilityRecord,
    FacilitySnapshot,
    LiftRecord,
)
from ..wire.facilities import StoredFacility, StoredFacilitySnapshot


def map_facility_snapshot(source: StoredFacilitySnapshot) -> FacilitySnapshot:
    return FacilitySnapshot(
        matched_by=source.matched_by,
        facility=_facility(source.facility) if source.facility is not None else None,
        lifts=tuple(
            LiftRecord(
                item.functional_location_code, item.description, item.record_updated_at
            )
            for item in source.lifts
        ),
        source_updated_at=source.source_updated_at,
        cache_stale=source.cache_stale,
    )


def _facility(source: StoredFacility) -> FacilityRecord:
    accessibility = source.accessibility
    coordinates = (
        FacilityCoordinates(source.latitude, source.longitude)
        if source.latitude is not None and source.longitude is not None
        else None
    )
    return FacilityRecord(
        name=source.name,
        efa_id=source.efa_id,
        tsn=source.tsn,
        address=source.address,
        phone=source.phone,
        coordinates=coordinates,
        transport_modes=source.transport_modes,
        accessibility_classification=_classification(accessibility),
        accessibility_features=accessibility[1:],
        facilities=source.facilities,
        morning_staffed_hours=source.morning_staffed_hours,
        afternoon_staffed_hours=source.afternoon_staffed_hours,
        short_platform=source.short_platform,
    )


def _classification(values: tuple[str, ...]) -> AccessibilityClassification:
    first = values[0].casefold() if values else ""
    if "independent access" in first:
        return "independent_access"
    if "assisted access" in first:
        return "assisted_access"
    if "not accessible" in first:
        return "not_accessible"
    return "unknown"
