# ADR-0006: SSH machine architecture — Repository, Session, Operations

- **Status:** Accepted
- **Date:** 2026-07-13
- **Supersedes:**
- **Superseded by:**

## Context

The SSH adapter connects the orchestrator to remote compute nodes and
keeps live state about each connection: which machine is busy, which is
free, what platform it runs, how long it has been idle. This state has
to be observed and mutated by multiple consumers — the orchestrator
producers, the cloud provisioner, the CLI status commands.

Two forces shaped the architecture:

- **Mixed responsibilities.** Collection state (which machines are
  connected, which are free) and per-machine operations (upload inputs,
  spawn a process, download outputs, probe occupancy) change at different
  rates and for different reasons. Collapsing them into one component
  produces a god-class that grows on every change.
- **Connection identity drift.** The hostname, port, username, and jump
  host needed to reach a node were being resolved at every connect from
  different sources, creating duplicated logic and opportunities for the
  stored identity and the resolved identity to diverge.

## Decision

The SSH adapter is organised into three architectural roles.

1. **Repository** holds the connected-machine collection. It owns the
  registry of live sessions, the connect/disconnect lifecycle, and the
  free/busy state queries. It is the single source of truth for "which
  machines are connected and in what state".

2. **Session** is a first-class entity per active connection. It carries
  the runtime state of one machine (its `ConnectedMachine` snapshot,
  free/busy transitions, the background occupancy monitor) and exposes
  the primitive SSH operations that act on that connection (run a
  command, upload, open SFTP). It owns its own teardown.

3. **Operations** are stateless collaborators that compose the Session
  primitives into use-case-shaped workflows (deploy a task, download
  outputs, check occupancy). They hold no state of their own — every
  call receives the session it acts on.

Connection identity — `hostname`, `port`, `username`, jump fields — lives
on `Node` and is immutable. It is resolved once at node creation (or
cloud allocation) and never re-derived at connect time.

`ConnectedMachine` carries only runtime-discovered fields (`node_id`,
`platform`, `state`, `free_since`). Anything that is a copy of `Node`
data is dropped — the canonical copy lives on `Node`.

The production DI path shares a single Repository instance across the
orchestrator and the cloud provisioner, so both see the same connection
registry.

## Alternatives Considered

### Single god-class for collection + operations

Rejected — collection and operations change for different reasons.
Collapsing them produces a component that grows on every change and
whose internal invariants become impossible to reason about.

### Domain handle + infra handle pair (split Session)

Rejected — every caller would have to thread two references instead of
one. One entity carrying both concerns is the lower-friction choice.

### Operations collaborators behind single-method Protocols

Rejected — three Protocols would inflate the port surface without
enabling any substitutability that a mock in tests does not already
cover. Concrete collaborator classes suffice.

### Lazy connection-identity resolution at first connect

Rejected — would introduce a write-on-read path through the SSH layer
and break the contract that `Node` is frozen identity. Identity is
resolved eagerly at creation.

## Consequences

- **Positive:** Each responsibility has exactly one owner; collection
  state, per-connection state, and use-case workflows evolve
  independently.
- **Positive:** One shared Repository means one connection registry; no
  duplicate connections to the same node, no leaks from competing
  instances.
- **Positive:** Connection identity is read once from `Node` and never
  re-derived; the SSH layer cannot drift away from the stored identity.
- **Positive:** `ConnectedMachine` carries only what is genuinely
  runtime; no stale copies of `Node` data to keep in sync.
- **Negative / trade-offs:** Operators who change `[remote].jump_host`
  in the INI after a node is registered must update the node row —
  identity is no longer re-resolved at runtime.
- **Accepted risks:** Single-instance Repository is a mutable shared
  resource; correctness depends on the orchestrator's cooperative
  scheduling, not on locking. Acceptable in a single-daemon process.
