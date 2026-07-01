## Context

A real Hetzner cloud run (`docs/CLOUD_BUGS.md`, 2026-06-30) exposed five
symptoms caused by a registry-vs-DB desync: `make_daemon` shares a single
`SSHMachineRepository` between `CloudProvisionerImpl._setup_vm` (which
calls `connect(ip)` registering a `FREE` session in `_sessions[ip]`
immediately) and `Orchestrator` (whose allocator reads `list_free()` on
the next tick). Because `connect` registers the session before the DB row
is enabled (`add_tmp` inserts `enabled=FALSE`; `_persist_node_with_cleanup`
flips it to `enabled=TRUE` only after setup succeeds), the allocator sees
a setup-in-flight node as free and dispatches tasks to it. Two secondary
gaps — SSH session leak on setup failure, and uncaught per-session
exceptions aborting the free-machine loop — compound the problem.

The existing unit tests mock `MachineRepository.list_free` directly, so
they never exercise the connect-before-enable timing and miss this class
of bug.

## Goals / Non-Goals

**Goals:**

- Restore the invariant: a machine is allocatable ONLY after its DB row is
  `enabled=TRUE`. The free-machine query intersects `list_free` with
  DB-enabled IPs (Fix A).
- Eliminate stale SSH sessions left by failed setup: `allocate` disconnects
  the session on the failure path before deleting the VM (Fix B).
- Ensure the cloud-provisioning branch is reachable even when a free-machine
  iteration raises: per-session `try/except` in the free-machine loop
  (Fix C).
- Improve cloud-init failure diagnosability: include `stdout` in the error
  message (Fix D).
- Add unit tests with timing-aware fakes that reproduce the registry-vs-DB
  desync and regression-guard all four fixes.

**Non-Goals:**

- Two-phase `connect`/`register` split on `MachineRepository` (rejected as
  YAGNI — Fix A's gate makes the class impossible in practice without
  changing the public Protocol).
- Moving the disconnect into `_setup_vm` via a context manager (B2
  structural — rejected; `allocate` already owns failure-handling, so
  colocating `disconnect` with `delete_node` is the minimal placement).
- Registry-level gate (registry refuses to list sessions whose IP is not
  DB-enabled — rejected; couples the SSH collection to `NodeRepository`,
  breaks layering).
- DB schema change, CLI change, public API change, or new dependencies.

## Decisions

### D1 — DB-enabled gate in the use case, not the registry

`_find_free_machines` reads `uow.nodes.list_enabled()` in the same UoW it
already opens for `uow.tasks.list_by_status({RUNNING})`, builds
`enabled_ips = {n.ip for n in enabled_nodes}`, and filters
`list_free(platforms)` by `s.machine.ip in enabled_ips`.

**Why the use case, not the registry:** `MachineRepository` is an SSH
collection port in the infrastructure layer; `NodeRepository` is a
persistence port. Making the registry query `NodeRepository` to filter its
sessions would couple SSH infrastructure to persistence — a layering
violation. The use case already holds a UoW and is the natural place to
join the two data sources.

**Why one UoW:** the existing code already opens `async with uow_factory()
as uow` to read running tasks. Adding `list_enabled()` inside the same
context adds one DB round-trip (cheap for small node counts) without a
second transaction.

**Side benefit:** a node that was disabled in DB but not yet disconnected
(the window between `deallocate_nodes.disable` and
`repository.disconnect`) also has a `FREE` session. The old filter (RUNNING
tasks only) would let it through; the new gate excludes it because its IP
is no longer in `enabled_ips`. This closes a second, latent desync window.

### D2 — Disconnect on setup failure in `allocate`, not `_setup_vm`

`CloudProvisionerImpl.allocate` already has two `except` blocks for the
`_setup_vm` call (`CloudSetupError` and generic `Exception`), both of which
call `adapter.delete_node`. Adding
`await self.machine_repository.disconnect(ip_addr)` before `delete_node` in
both blocks is a one-line-per-block change in the existing failure path.

**Why not B2 (context manager inside `_setup_vm`):** `_setup_vm` currently
has no try/except around the full body — it lets exceptions propagate to
`allocate`, which owns failure handling (logging + `delete_node`). Moving
disconnect into `_setup_vm` would require adding a new try/except there,
duplicating the failure-handling ownership. Keeping disconnect next to
`delete_node` in `allocate` is consistent with the existing structure and
minimal (AGENTS.md: "prefer minimal changes over broad refactors").

**Success path unchanged:** on success, `_setup_vm` returns `Node` and the
session stays registered. The orchestrator reuses the connection on the
next tick (now visible because `_persist_node_with_cleanup` flipped the DB
row to `enabled=TRUE`). This is the designed behavior — Fix A does not
break it (the session's IP is in `enabled_ips`).

### D3 — Per-session try/except, log, continue — no disconnect

`_allocate_free_machine` wraps each `_try_start_on_machine` in
`try/except Exception as err: logger.error(...); continue`.

**Why no `disconnect` in the except:** a transient SSH failure on a
legitimately-connected node (e.g. a momentary network blip) does not mean
the session is dead — the node may recover, and the session's monitor task
manages its lifecycle. Disconnecting on every exception would tear down
connections that could have recovered. Stale sessions (the case that
matters) are already prevented at the source by Fix B's mid-run disconnect
on setup failure. Fix C is defense-in-depth: it ensures the loop reaches
the cloud branch even if a session fails for any reason.

**Log level `error`:** matches the existing `"Allocator error for task N"`
in `_allocator_consumer` (orchestrator.py:407). The session failure is
per-task, per-session — logged with task_id and ip for traceability.

### D4 — `stdout` in the cloud-init error message

`_setup_vm` CLOUD_INIT block: add `stdout={result.stdout}` to the
`CloudSetupError` f-string alongside the existing `stderr=`. One-line
change. `cloud-init status --wait` writes its status line to stdout, so
the current `stderr=` (typically empty) gives no clue why it failed.

## Risks / Trade-offs

- **[Extra DB read per allocate tick]** → `list_enabled()` adds one query
  per `_find_free_machines` call. Node counts are small (tens at most),
  and the query is already filtered to valid IPs. Acceptable cost for the
  invariant guarantee. If profiling later shows this is hot, a targeted
  `get_by_ips(free_ips)` lookup could replace it — not needed now.

- **[Stale `enabled_ips` under concurrent enable]** → `list_enabled()` is
  read in a separate UoW from the one that persists the node. A node could
  be enabled after `list_enabled()` returns but before the filter applies.
  This is benign: the next tick's `list_enabled()` includes it. The
  allocator simply doesn't see it on this tick — it sees it on the next.
  This matches the existing one-tick lag for `list_by_status({RUNNING})`.

- **[Fix C masks persistent session failures]** → a session that
  consistently raises would be logged and skipped every tick, never
  disconnected by Fix C. Mitigation: the session's monitor task and the
  deallocate loop handle persistent failures independently. If a session
  is truly dead (SSH closed), `is_closed` is set synchronously and the
  monitor/deallocate path removes it. Fix C is not the cleanup mechanism —
  it's the "don't abort the loop" mechanism.

- **[Fix B disconnect on a session that was never connected]** → if
  `_connect_to_vm` itself fails (SSH connect error), it raises
  `CloudSetupError` before `connect` registers the session. Then
  `allocate`'s `except` block calls `disconnect(ip_addr)` on an IP not in
  `_sessions`. `SSHMachineRepository.disconnect` handles this: it does
  `self._sessions.pop(ip, None)` and returns `None` if absent. Safe no-op.

## Migration Plan

No migration required. All changes are in-memory behavior fixes with no
schema, config, or API change. Deploying the new daemon binary
immediately fixes the bugs for running tasks on the next tick.

Rollback: revert to the previous binary. No data migration needed.

## Open Questions

None — all decisions resolved during exploration.