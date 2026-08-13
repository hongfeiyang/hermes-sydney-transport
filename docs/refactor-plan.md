# Layer migration plan

Status: **completed**. This file records the migration sequence; the normative current
design is `docs/architecture.md`.

The architecture contract is in force immediately. This plan moves the verified 0.4
implementation without changing tool names or public schemas.

## Ground rules

- New capabilities start in target layers.
- Each phase is behavior-preserving and releasable; no big-bang branch.
- Move one vertical slice at a time from request through presentation.
- Existing live outputs become characterization fixtures before moving a slice.
- The former mixed root modules were deleted after all production imports moved.

## Phase 0 — contracts and enforcement (complete)

- Normative layer and stage contracts.
- Machine-readable dependency/capability policy.
- CI architecture checks.
- Closed flat-module allowlist and no-growth budgets.
- Target package scaffolding.

Exit criterion: the complete existing test suite plus architecture checks is green.

## Phase 1 — shared primitives

Create:

- `models/errors.py`: stable domain error code/value types;
- `ports/clock.py`: `Clock.now() -> datetime`;
- `adapters/system_clock.py`: production clock;
- `bootstrap/settings.py`: validated immutable settings from the environment;
- `presentation/envelopes.py`: the only domain-error-to-Hermes mapping.

Move the shared domain error out of the mixed Trip Planner module. Remove direct
clock/environment access from application-facing code.

Exit criterion: error mapping and fixed-clock behavior are contract-tested; legacy
modules are smaller; no tool output changes.

## Phase 2 — migrate NSW Traffic Volume as the first vertical slice

It is the smallest independent pipeline and exercises the full design.

Create:

```text
ports/traffic_counts.py
application/traffic/search_stations.py
application/traffic/get_summary.py
application/traffic/get_hourly.py
adapters/tfnsw/traffic_volume_http.py
adapters/tfnsw/traffic_volume_mapper.py
presentation/traffic_tools.py
bootstrap/traffic.py
```

The port exposes three semantic operations and typed source records. SQL-shaped wire
queries remain entirely inside the adapter. Move code out of the former traffic root
module, then delete it.

Exit criterion: the three live tools have identical request/result schemas, adapter
tests cover permanent/sample type drift, and application tests contain no HTTP mocks.

## Phase 3 — migrate Trip Planner

Split acquisition, wire contracts, normalization, and five use cases:

```text
ports/trip_planner.py
application/trip_planner/*
adapters/tfnsw/trip_planner_http.py
adapters/tfnsw/trip_planner_wire.py
adapters/tfnsw/trip_planner_mapper.py
presentation/trip_planner_tools.py
```

Preserve macro policy in the adapter and mode/certainty policy in application. Remove
Move HTTP, HTML parsing, and normalization from the former mixed module; delete it
after compatibility imports are gone.

Exit criterion: no application test imports `urllib` or uses raw TfNSW mappings.

## Phase 4 — migrate realtime and static GTFS

Create separate ports for feed acquisition and schedule lookup. Keep protobuf and CSV
records adapter-owned; expose typed trip, stop-update, vehicle, and schedule records.
Move cancellation precedence, progress, stop change, prediction, and confidence into
application use cases.

```text
ports/realtime.py
ports/static_schedule.py
application/realtime/*
adapters/tfnsw/gtfs_realtime_http.py
adapters/tfnsw/gtfs_realtime_decoder.py
adapters/tfnsw/static_gtfs_repository.py
presentation/realtime_tools.py
```

Exit criterion: train/bus use cases differ through explicit policy/configuration, not
conditionals in transports; the former realtime root modules are removed.

## Phase 5 — presentation and composition cleanup

- Replace duplicate schema/handler tables with one `ToolSpec` catalog and generic
  handler generation.
- Move factories and environment checks into `bootstrap/`.
- Reduce package `register(ctx)` to composition-root delegation.
- Remove all legacy exceptions and line budgets from `architecture.toml`.

Exit criterion: every runtime module is owned by a target layer, the dependency matrix
passes with no legacy rules, directory and wheel PluginManager smokes pass, and a
credentialed check covers all tool families.
