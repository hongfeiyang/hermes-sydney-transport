# Multimode transport implementation tracker

Status: release candidate
Target release: 0.6.0

This tracker records the capabilities that were targeted for 0.6.0. Each capability
follows the single extension path in `docs/architecture.md` and is considered
implemented only when contracts, ports, application policy, adapters, presentation,
bootstrap, deterministic tests, architecture checks, and user documentation agree.

## Source contracts

- [x] Trip Planner OpenAPI and technical documentation
- [x] GTFS and GTFS-Realtime implementation specification
- [x] GTFS static schedule v1 and v2 OpenAPI definitions
- [x] GTFS-Realtime Trip Updates v1 and v2 OpenAPI definitions
- [x] GTFS-Realtime Vehicle Positions v1 and v2 OpenAPI definitions
- [x] GTFS-Realtime Alerts v2 OpenAPI definition
- [x] TfNSW protobuf extension definitions
- [x] Complete GTFS and Pathways documentation
- [x] Live Traffic Hazards OpenAPI and developer guide
- [x] Interchange facilities, lift, and location-facilities data dictionaries
- [x] NSW Traffic Volume Counts OpenAPI and dataset documentation

Upstream source files remain local research inputs and are not committed to this
public repository. Tests use small sanitized fixtures only.

## P1 — route disruptions

- [x] Add strict route-disruption request and result models
- [x] Add a semantic alerts port and immutable source records
- [x] Decode bounded GTFS-Realtime Alerts v2 feeds
- [x] Aggregate and deduplicate mode feeds deterministically
- [x] Support route, stop, trip, mode, cause, and effect filtering
- [x] Preserve active periods, severity, uncertainty, and unresolved selectors
- [x] Register `sydney_transport_route_disruptions`
- [x] Add adapter, application, schema, envelope, and registration tests

## P1 — live road hazards

- [x] Add strict location/suburb/radius/type request contract
- [x] Add typed hazard and GeoJSON source contracts
- [x] Query only allowlisted current hazard endpoints
- [x] Bound feature counts, response bytes, text, coordinates, and time ranges
- [x] Calculate proximity without exposing a generic URL or query language
- [x] Register `nsw_live_traffic_hazards`
- [x] Add deterministic normalization and failure-path tests

## P1 — stop accessibility

- [x] Add strict stop accessibility request and result models
- [x] Add a semantic facilities port and immutable records
- [x] Index the current location-facilities and lift datasets behind the adapter
- [x] Distinguish static facilities from current accessibility warnings
- [x] Preserve source date, audit quality, and unknown lift state
- [x] Register `sydney_transport_stop_accessibility`
- [x] Add indexing, matching, output, and unavailable-data tests

## P2 — route timetable

- [x] Add strict route/date/direction/stop timetable contracts
- [x] Add a semantic timetable port
- [x] Build a bounded SQLite index from Complete GTFS
- [x] Apply `calendar.txt` and `calendar_dates.txt` correctly
- [x] Keep Complete GTFS identifiers separate from realtime-feed identifiers
- [x] Return bounded ordered trips and stop times with provenance
- [x] Register `sydney_transport_route_timetable`
- [x] Add calendar exception, overnight time, direction, and bounds tests

## P2 — Metro, light rail, and ferry

- [x] Extend public mode contracts without duplicating use cases
- [x] Add allowlisted static, Trip Updates, Vehicle Positions, and Alerts feed policies
- [x] Define mode-specific cancellation, occupancy, platform/stop, and confidence policy
- [x] Extend search, departures, planning, and Trip Planner alerts to all five modes
- [x] Extend route disruptions, service status, and vehicle position through the existing pipeline
- [x] Add per-mode feed, static join, coverage, and regression tests

## Release gates

- [x] `./scripts/verify.sh architecture`
- [x] `./scripts/verify.sh lint`
- [x] `./scripts/verify.sh types`
- [x] `./scripts/verify.sh test`
- [x] `./scripts/verify.sh package`
- [x] Real Hermes `PluginManager` directory-load smoke
- [x] Credentialed TfNSW smoke without logging secrets or response bodies
- [x] README, tool reference, architecture notes, and manifest updated
- [x] Version raised consistently

Runtime verification used Hermes 0.20.0 on Python 3.13.5. The real directory loader
registered all 22 tools with no plugin error. Bounded live calls covered Trip Planner
stop search, Alerts v2 route disruptions, Live Traffic hazards, an exact Central
accessibility lookup, and a Complete GTFS route timetable lookup. Verification logged
only success, counts, provenance, and error metadata; it did not log credentials or
upstream response bodies.
