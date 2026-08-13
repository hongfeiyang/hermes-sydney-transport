# ADR 0002: Typed realtime snapshots and indexed static GTFS

Status: Accepted
Date: 2026-08-13

## Context

The first layered implementation kept GTFS-Realtime and static GTFS records as
`TypedDict` values containing timestamp strings. Its 851-line realtime application
class fetched and decoded physical feeds, repeatedly parsed time text, joined stops,
applied business policy, and assembled output. Static trip cache misses rescanned the
large compressed CSV tables. The behavior was correct but the boundary was still
stringly typed and expensive to extend.

## Decision

- Protobuf and CSV adapters convert external values once into frozen, slotted
  dataclasses containing typed dates, datetimes, durations, enums, and tuples.
- Application code depends on semantic `RealtimeRepository` and
  `StaticSchedulePort` interfaces. It cannot receive transports, decoders, endpoint
  names, protobuf messages, or mutable record dictionaries.
- Realtime interpretation uses one ordered pipeline: resolve, snapshot, static join,
  timeline, policy, result. Train and bus differences are one `ModePolicy` value.
- Each realtime feed is protected by a bounded, thread-safe TTL cache and indexed by
  exact service ID after one decode.
- Each static GTFS refresh is bounded and atomically indexed into SQLite. Application
  code requests a trip and a batch of stops through semantic methods.
- The composition root is reused for identical validated settings so these caches
  survive across Hermes handler calls.
- `architecture.toml` enforces no `Any`/`TypedDict` in ports/application, immutable
  port records, no application time parsing or feed identifiers, and application
  module-size and complexity ceilings.

## Consequences

Manual protobuf presence and extension mapping remains explicit in the TfNSW decoder,
where it is auditable. Application policies become small pure functions over typed
values. Static refresh performs more work once but subsequent trip/stop queries use
indexes. Cache behavior and the architectural bans require deterministic regression
tests. A schema or policy change must update its owned layer rather than adding a
parallel realtime path.
