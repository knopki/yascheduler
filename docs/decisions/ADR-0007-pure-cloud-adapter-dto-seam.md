# ADR-0007: Pure cloud adapter with provider-DTO seam

- **Status:** Accepted
- **Date:** 2026-07-18
- **Supersedes:**
- **Superseded by:**

## Context

The cloud adapter provisions and tears down VMs across multiple providers
(Hetzner, Azure, UpCloud, VastAI). Early on, it was tangled with node
persistence: cloud operations opened DB connections, wrote to
`yascheduler_nodes` directly, and mixed cloud-API latency (minutes) with
short DB transactions.

The forces at play:

- **Mixed responsibilities.** Cloud-API calls and node persistence change
  for different reasons and operate on different timescales. Mixing them
  in one component hides transaction boundaries and makes the cloud
  adapter untestable without a database.
- **Provider specifics leaking into the domain.** Each provider exposes
  its own configuration shape (auth tokens, server types, regions). If
  those reach the domain layer, every new provider widens the domain's
  surface and couples application logic to provider vocabulary.

## Decision

1. **The cloud adapter is pure.** It contains only cloud-API calls — no
  DB, no UoW. Node persistence is owned by use cases, which call the
  cloud adapter through the `CloudProvisioner` port and then persist the
  result. This mirrors the SSH adapter's purity (ADR-0006).

2. **The cloud contract exposed to the application is narrow and
  provider-agnostic.** A `CloudConfig` Protocol in the domain defines
  the minimal set of fields application consumers actually read. Every
  provider-specific field (token, server type, package upgrade flag,
  etc.) lives on concrete DTOs in `infra/cloud/`, never on the Protocol.

3. **`external_id` and `hostname` are distinct identity roles.** When a
  provider creates a node, it returns both: `external_id` is the
  provider-native resource identifier used for O(1) provider lookups
  (e.g. Hetzner numeric server ID); `hostname` is the SSH address. The
  two must not collapse into one field — a node's hostname may change
  while its provider identity remains stable.

4. **`CloudError` is the domain root for cloud failures.** Cloud
  operational errors (`CloudAllocateError`, `CloudSetupError`) inherit
  from `DomainError` via a `CloudError` intermediate root, so all
  domain failures remain catchable through a single base. Capacity
  exhaustion stays separate — it is a scheduling signal, not an SDK
  failure.

## Alternatives Considered

### Cloud adapter with DB access (pass UoW as parameter)

Rejected — cloud operations run for minutes; holding a DB transaction
across them is wrong. Persistence belongs to the use case, which owns
the transaction boundary.

### Wide `CloudConfig` Protocol exposing provider fields

Rejected — would couple the domain to provider vocabulary and force
every provider change to ripple through the domain. The narrow
application-surface Protocol follows interface segregation.

### Use hostname as the sole node identity on the provider side

Rejected — hostname is mutable (DNS, reboots, re-IP) and not
provider-native. A provider lookup keyed by hostname requires search;
keyed by `external_id` is O(1) and survives hostname changes.

### Flat cloud exception hierarchy

Rejected — flattening `CloudAllocateError` / `CloudSetupError` directly
under `DomainError` loses the grouping that lets callers distinguish
"the cloud SDK failed" from other domain failures.

## Consequences

- **Positive:** The cloud adapter is testable without a database; cloud
  flows can be mocked at the `CloudProvisioner` port boundary.
- **Positive:** The domain stays provider-agnostic — adding a provider
  touches `infra/cloud/` and the parser registry, not the domain.
- **Positive:** Provider lookups during teardown are O(1) by
  `external_id`; no fragile hostname search.
- **Positive:** All cloud failures catchable via `CloudError`; capacity
  exhaustion remains a distinct scheduling signal.
- **Negative / trade-offs:** Two concepts for one node (`external_id`
  vs `hostname`) — consumers must learn which to use for which purpose.
- **Negative / trade-offs:** Provider DTOs carry fields the Protocol
  hides from the application; consumers below the application layer
  must reach for the concrete DTO type.
- **Accepted risks:** Existing providers that use IP as `external_id`
  (Azure, UpCloud, VastAI) keep that convention; only Hetzner uses a
  provider-native numeric ID today. The split contract supports both;
  migrating the rest is opportunistic.
