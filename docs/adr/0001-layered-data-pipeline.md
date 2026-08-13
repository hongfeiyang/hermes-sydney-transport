# ADR 0001: Layered ports-and-adapters data pipeline

- Status: Accepted
- Date: 2026-08-13

## Context

Version 0.4 added train, bus, and road-count capabilities successfully, but the main
modules grew around sources rather than architectural boundaries. HTTP acquisition,
wire decoding, normalization, business policy, time, and result construction can live
in the same file. File separation alone does not prevent future features from adding
logic wherever convenient.

## Decision

Adopt the normative layer contract in `docs/architecture.md` and the machine-readable
policy in `architecture.toml`.

Use canonical Pydantic models at presentation/application boundaries, consumer-owned
Protocols for ports, typed source DTOs at adapter boundaries, constructor injection,
and a single bootstrap composition root. Dependencies point inward; external details
remain in adapters.

Treat the then-current mixed root modules as temporary legacy code under a no-growth
ratchet. Migrate with a strangler approach so each step is behavior-preserving and
independently releasable. The migration is now complete; the final policy has no
legacy exceptions.

## Consequences

Positive:

- layer ownership and review expectations are explicit;
- use cases can be tested without network, environment, Hermes, protobuf, or files;
- source-specific drift is contained in one adapter;
- schemas and public results remain stable while adapters change;
- CI rejects dependency inversion and renewed growth of mixed modules.

Costs:

- more small modules and explicit DTO conversions;
- initial migration work before substantial new features;
- shared concepts require deliberate ownership rather than opportunistic reuse.

## Rejected alternatives

- **Keep feature-oriented root files:** easy initially but does not control coupling.
- **One generic provider client:** leaks URLs/query shapes and encourages raw payloads.
- **Repository pattern for every source:** too persistence-centric; semantic ports
  better describe transit and traffic capabilities.
- **Big-bang rewrite:** risks regression in already verified live behavior. The
  strangler migration preserves the running plugin while moving one pipeline at a
  time.
