# Declarative adapter refactor tracker

Status: complete; version 0.7.1 is deployed and verified in Hermes

This tracker turns the adapter design into an executable contract. A phase is complete
only when its checker rules, mutation-style architecture tests, deterministic contract
tests, type checks, and affected runtime paths all agree. Temporary allowlists,
grandfathered violations, and raised budgets are not accepted.

## Baseline recorded on 2026-08-14

- [x] Confirm the repository is clean at `fa63531` before refactoring
- [x] Record 5,069 handwritten lines under `adapters/tfnsw`
- [x] Record 57 `try` blocks under `adapters/tfnsw`
- [x] Record five separate authenticated HTTP/retry implementations
- [x] Confirm adapter modules are not covered by existing line or complexity budgets
- [x] Confirm application code still contains nested dictionary projection paths
- [x] Confirm feature adapters import helpers from other feature adapters

## P0 — executable adapter grammar

- [x] Add machine-readable transport, codec, wire, mapper, repository, and endpoint
  ownership to `architecture.toml`
- [x] Restrict network-library imports and API-key header construction to one transport
  module
- [x] Restrict JSON, CSV, ZIP, XLSX/XML, and protobuf parsing to declared codec modules
- [x] Forbid feature-adapter-to-feature-adapter imports
- [x] Forbid `try` blocks in repositories and mappers
- [x] Forbid raw nested dictionary projection into Pydantic models in application code
- [x] Apply module-size and function-complexity budgets to all handwritten runtime code
- [x] Add Ruff complexity, branch, statement, and exception checks
- [x] Add mutation-style tests proving every new rule fails on a violating fixture
- [x] Run the stricter checker against the current tree and retain the violations as the
  refactor worklist, not as an allowlist

## P0 — harness escape-route closure

- [x] Make each `ModeSpec` row own mode, policy, Alerts sources, every realtime/static
  feed, cache namespace, and both realtime capabilities
- [x] Remove repository defaults and parallel mode-keyed endpoint/source/policy tables;
  inject every mode binding from the composition root
- [x] Reject top-level `TransportMode` registries and explicit per-mode binding branches
  outside `bootstrap/modes.py`
- [x] Reject byte decoding, line splitting, `datetime.strptime`, `HTMLParser`, and
  dict-to-model parsing inside repositories and mappers
- [x] Move HTML decoding and legacy delimited cache fields into bounded codecs
- [x] Require public wire records, including nested wire modules, to inherit from the
  configured `WireModel` family instead of arbitrary `BaseModel`
- [x] Reject direct, aliased, qualified, and postponed-string `Any`/`TypedDict` use in
  typed adapter roles
- [x] Add mutation fixtures proving each escape route makes the checker fail

## P0 — shared transport and errors

- [x] Add one validated `EndpointSpec` catalog for every TfNSW endpoint
- [x] Add one persistent authenticated HTTP client
- [x] Reject redirects centrally
- [x] Enforce timeouts, response-byte limits, conditional requests, and content types
  centrally
- [x] Implement one declarative retry/backoff policy
- [x] Translate HTTP and network failures into the canonical error taxonomy centrally
- [x] Add a reusable transport contract suite covering auth, redirects, retry, 304,
  timeout, oversized responses, error closure, and secret redaction

## P0 — codecs and canonical contracts

- [x] Add one generic Pydantic JSON codec using `model_validate_json`
- [x] Add reusable constrained scalar types for normalized text, URLs, coordinates,
  epoch timestamps, identifiers, and finite numeric values
- [x] Add canonical frozen Pydantic domain models for semantic adapter outputs
- [x] Align public nested result models with canonical domain models where semantics are
  identical
- [x] Represent expected partial-source availability as typed data instead of exception
  control flow
- [x] Add malformed, oversized, unknown-field, boundary, and property-based codec tests

## Reference slice — Live Traffic

- [x] Move Live Traffic endpoints into the endpoint catalog
- [x] Replace its private urllib/retry/error implementation with the shared transport
- [x] Move GeoJSON decoding and aliases into a strict wire codec
- [x] Move normalization into constrained wire/domain types
- [x] Keep filtering, distance, ordering, and bounds in a small pure mapper/repository
- [x] Remove manual nested output dictionaries from the application use case
- [x] Keep suburb matching against complete upstream roads while bounding returned roads
- [x] Pass architecture, lint, strict typing, and deterministic tests
- [x] Repeat bounded credentialed smoke against the refactored installed build

## Remaining migrations

- [x] Move GTFS-Realtime binary feeds and Alerts to the shared transport
- [x] Move Traffic Volume Counts JSON to the shared transport and JSON codec
- [x] Move Trip Planner JSON to the shared transport and typed wire models
- [x] Replace static-resource HTTP with the shared transport/download sink
- [x] Express facilities CSV and lift workbook parsing behind declared codecs
- [x] Express Complete GTFS and mode-static GTFS ingestion through table specifications
  while preserving streaming performance
- [x] Remove feature-to-feature helper imports
- [x] Replace repeated train/bus/metro/light-rail/ferry construction with one `ModeSpec`
  registry
- [x] Delete superseded transports, parsers, helpers, and compatibility paths

## Release gates

- [x] `./scripts/verify.sh architecture`
- [x] `./scripts/verify.sh lint`
- [x] `./scripts/verify.sh types`
- [x] `./scripts/verify.sh test`
- [x] `./scripts/verify.sh package`
- [x] One-command `./scripts/verify.sh all` in the Python 3.12 development environment
- [x] Python 3.12 and 3.13 CI configuration
- [x] Minimum-dependency CI configuration
- [x] Real Hermes `PluginManager` load with exactly 22 tools
- [x] Bounded credentialed Trip Planner, Alerts, Live Traffic, accessibility, and
  timetable smoke tests without secrets or response bodies
- [x] Installed plugin contains no superseded modules
- [x] Repository is clean, committed, and synchronized with public `main`

## Deployment evidence recorded on 2026-08-14

- [x] Native directory and wheel entry-point loading both register the exact 22-tool
  manifest under Hermes 0.20.0
- [x] Live Trip Planner stop search and Alerts return validated results
- [x] Live Alerts v2 route disruptions and NSW Live Traffic hazards return validated
  results
- [x] Static facilities automatically migrate cache schema v1 to v2 and return a
  validated accessibility result
- [x] Complete GTFS returns a validated timetable result and a new process reuses the
  persistent 540 MB index; the measured warm query completed in 0.08 seconds
- [x] The live checks printed only status/count metadata; no credential or provider
  response body was recorded
