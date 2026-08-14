# Changelog

## 0.7.2 - 2026-08-14

- Replaced version-sensitive `strict=False` datetime coercion with one shared,
  declarative Pydantic wire timestamp contract.
- Model the two official Live Traffic time representations explicitly: bounded epoch
  milliseconds or timezone-aware ISO 8601 text.
- Reject naive timestamps, date-only strings, numeric strings, floats, booleans and
  out-of-range epochs through the canonical codec error path.
- Added an architecture gate that prevents timestamp parsing from being reintroduced
  outside `wire/timestamps.py`, plus cross-provider timestamp contract tests.
- Verified the complete 120-test suite against both minimum Pydantic 2.9 and the current
  supported dependency set.

## 0.7.1 - 2026-08-14

- Accept the bounded network-wide route and stop lists returned by live Trip Planner
  alerts; the former limit of 20 rejected valid current TfNSW responses.
- Add a regression contract using the affected-entity cardinalities observed in the
  live provider response.
- Persist the Complete GTFS refresh window so a new Hermes process reuses the warm
  540 MB timetable index instead of downloading and rebuilding it again.

## 0.7.0 - 2026-08-14

- Refactored every TfNSW integration into one enforced catalogs/platform/codecs/wire/
  mappers/stores/repositories pipeline.
- Added mutation-tested architecture gates for the single tool and transport-mode
  extension paths, parsing boundaries, shared wire family, typing, size and complexity.
- Consolidated HTTP authentication, retry, redirect, timeout, response limits and error
  translation into one persistent transport.
- Replaced raw provider projections with strict Pydantic wire contracts and typed
  availability results.
- Added atomic static-resource caches, conditional mode-GTFS refresh and automatic
  facilities cache migration to schema v2.

## 0.6.0 - 2026-08-14

- Expand the public tool catalog to 22 tools across `sydney_transport` and
  `nsw_traffic`, covering five realtime public-transport modes plus static
  accessibility, Complete GTFS route timetables, live road hazards, and historical
  road-count data.
- Add `sydney_transport_route_disruptions` backed by GTFS-Realtime Alerts v2 with
  mode, cause, effect, severity, active-period filtering, and exact source-feed
  provenance across `sydneytrains`, `nswtrains`, `buses`, `regionbuses`, `metro`,
  `lightrail`, and `ferries`.
- Add `sydney_transport_stop_accessibility`, combining exact-stop static facilities
  and interchange lifts with optional current accessibility warnings while keeping
  static inventory distinct from current operational status.
- Add `sydney_transport_route_timetable`, backed by a bounded Complete GTFS SQLite
  index and explicit namespace separation between Complete GTFS identifiers and
  realtime `service_id` values.
- Extend service-status and vehicle-position tools to metro, light rail, and ferry
  with mode-specific static and realtime feed policy.
- Extend Trip Planner stop search, departures, journey planning, and alerts to all
  five public-transport modes while retaining the train-plus-bus default.
- Add `nsw_live_traffic_hazards`, using strict GeoJSON wire validation over
  allowlisted current hazard feeds with suburb or coordinate/radius filtering;
  accept the integer and finite numeric hazard IDs both emitted by the live API.
- Align release metadata, manifests, AI-facing docs, and packaging tests so
  `plugin.yaml`, Python metadata, and the catalog expose the same 22 tools.

## 0.5.0 - 2026-08-13

- Raise the Python baseline to 3.12 and use PEP 695 type-parameter syntax.
- Fix persisted static-GTFS indexes skipping their first conditional refresh when the
  process monotonic clock is below the six-hour cache window.
- Add public installation, tool-reference, runtime-pipeline, security and AI discovery
  documentation; remove machine-specific paths and personal author metadata.
- Replace realtime `TypedDict`/timestamp-string boundaries with frozen, slotted
  dataclasses, enums, aware datetimes, durations, and a GTFS service-time value type.
- Move feed acquisition and protobuf decoding behind a semantic realtime repository
  with a bounded, thread-safe single-flight cache and exact service-ID indexes.
- Split the realtime application into resolver, timeline, cancellation, progress,
  confidence, occupancy, vehicle projection, and thin service/vehicle use cases.
- Replace repeated static CSV scans with an atomically built SQLite index and batch
  stop lookup; reuse the composition root across calls for unchanged settings.
- Enforce architecture gates for immutable port records, no `Any`/`TypedDict` or
  manual time parsing in application code, no feed endpoint leakage, module and
  branch complexity ceilings, and no nested realtime loops.

## 0.4.0 - 2026-08-12

- Rename the standalone plugin, package, toolset, and model-visible tool namespace to
  Sydney Transport, with one canonical `hermes_sydney_transport` import path.
- Add train/bus mode selection to stop search, departures, trip planning, and alerts.
- Add bus Trip Updates and Vehicle Positions tools with bus-specific cancellation,
  delay, occupancy, static-GTFS, and coverage policy.
- Add three NSW Roads Traffic Volume Counts tools for station lookup, yearly
  summaries, and bounded hourly permanent/sample data.
- Generate all 12 Hermes schemas from strict Pydantic models. The road tools expose
  only fixed allowlisted query templates; caller-provided SQL is never accepted.
- Split Hermes registration into `sydney_transport` and `nsw_traffic` toolsets while
  continuing to use one private `TFNSW_API_KEY` secret.

## 0.3.0 - 2026-08-12

- Add `sydney_trains_service_status` backed by GTFS-Realtime Trip Updates and the
  current Sydney Trains static GTFS bundle, including next-stop predictions,
  cancellations, skipped stops, replacements, and platform changes.
- Add `sydney_trains_vehicle_position` with reported coordinates, current movement
  state, optional vehicle metadata, whole-train occupancy, and TfNSW per-carriage
  occupancy extensions.
- Expose the exact `service_id` on departures. Preserve `trip_code + stop_id` as a
  bounded fallback resolver instead of incorrectly treating Trip Planner trip codes
  as GTFS trip IDs.
- Vendor the official TfNSW GTFS-Realtime extension schema and compatible generated
  Python binding; hide realtime tools when protobuf support is unavailable.
- Add bounded binary transports, six-hour conditional static-GTFS caching, a 64-trip
  LRU, confidence/data-quality contracts, and mocked protobuf/static-GTFS tests.
- Preserve UpdateBundle identity and sequence, report cancellation provenance, and
  fail closed on bundle-only evidence because the public static ZIP exposes no
  comparable bundle identity.
- Represent vehicle stop context as explicit at/last-passed/target fields with an
  inference flag; correct the TfNSW wheelchair enum and prefer static platform codes.

## 0.2.0 - 2026-08-12

- Add nearby public-transport stop lookup through `/coord` and
  `PoisOnMapMacro`, with platform-to-stop deduplication.
- Add train-mode journey planning through `/trip`, using `depArrMacro` and
  `TfNSWTR`, including depart-after/arrive-by, wheelchair filtering, realtime
  timestamps, legs, platforms, operators, alerts, and bounded stop sequences.
- Document every Trip Planner macro used by the plugin and verify the new
  endpoints against the current TfNSW engine.
- Replace hand-written argument validation and schemas with separate Pydantic v2
  input/output contracts and generated Hermes JSON Schemas.

## 0.1.1 - 2026-08-12

- Use the current Trip Planner station-search contract (`type_sf=any`) and
  filter train stops locally; the current engine rejects `type_sf=stop`.

## 0.1.0 - 2026-08-12

- Add station search, train departures, and current alert tools.
- Add bounded HTTPS transport, retry policy, validation, Australia/Sydney timezone
  handling, alert plaintext normalization, and stable JSON envelopes.
- Support native Hermes directory installation and pip entry-point discovery.
