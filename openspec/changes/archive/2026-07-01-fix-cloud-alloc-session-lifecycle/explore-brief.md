# Explore Brief — fix-cloud-alloc-session-lifecycle

## Problem

Real Hetzner run (`docs/CLOUD_BUGS.md`, 2026-06-30): 1 cloud, 6 TO_DO. Five
symptoms, one architectural root cause + two secondary gaps.

**Root cause**: shared `SSHMachineRepository` (`di.py:156,182,212`) injected
into both `CloudProvisionerImpl` (used by `_setup_vm`) and `Orchestrator`
(used by allocator). `connect(ip)` registers a `SSHMachineSession` in
`_sessions[ip]` **immediately** (`repository.py:240`), with
`state=FREE, free_since=now`, while the DB row is still the tmp-node
(`enabled=FALSE`, `add_tmp` at `postgres.py:330`). The orchestrator's
`list_free()` sees this session on the next tick — **before setup
completes**. Source of symptoms 1 (task on not-setup node), 2 (race pile-on),
5 (task orphaned when node deleted).

**Bug 2**: `_setup_vm` failure deletes the VM in the cloud but does NOT
`disconnect(ip)` the SSH session. Stale `FREE` session lingers in
`_sessions` for the daemon's lifetime → allocator picks it →
`ChannelOpenError` (symptom 4: no new nodes after 2 failures).

**Bug 3**: `_allocate_free_machine` loop does not isolate per-session
failures — one stale session's `ChannelOpenError` aborts the whole loop,
cloud branch never reached (symptom 4).

**Bug 4** (minor): cloud-init error message omits `stdout=` (status line
goes to stdout) — pure diagnosability gap.

## Rejected alternatives

- **Two-phase registration** (`connect` ≠ `register`, gate visibility on
  setup completion): eliminates the class by construction but changes the
  public `MachineRepository` Protocol. YAGNI — Fix A's DB-enabled gate
  makes the bug impossible on practice; defense-in-depth not needed.
- **B2 structural** (move disconnect into `_setup_vm` via context manager):
  symmetric but adds new try/except inside `_setup_vm`. `allocate` already
  owns failure-handling for setup (`delete_node` is there); `disconnect`
  colocated with `delete_node` is the minimal, consistent placement. AGENTS.md
  "prefer minimal changes".
- **Registry-level gate** (registry refuses to list sessions whose IP is
  not DB-enabled): couples SSH collection to `NodeRepository` — breaks
  layering. Gate belongs in the use case.

## Final approach

| Fix | Where | What |
|-----|-------|------|
| A   | `allocate_task.py:_find_free_machines` | Intersect `list_free(platforms)` with `enabled_ips = {n.ip for n in await uow.nodes.list_enabled()}` in the same UoW. Restores invariant: allocatable ⇒ enabled in DB. |
| B1  | `manager.py:CloudProvisionerImpl.allocate` (both `except` blocks) | `await self.machine_repository.disconnect(ip_addr)` before `adapter.delete_node` on setup failure. Mid-run drain; `stop()` remains shutdown drain. |
| C   | `allocate_task.py:_allocate_free_machine` | `try/except Exception` around each `_try_start_on_machine`; `logger.error` + `continue`. NO `disconnect` in except — transient SSH failure ≠ dead session; monitor owns state. |
| D   | `manager.py:_setup_vm` CLOUD_INIT block | Add `stdout={result.stdout}` to `CloudSetupError`. |

## Cross-module data flows

```
CloudProvisionerImpl._setup_vm
  → _connect_to_vm → machine_repository.connect(ip)  [registers session, FREE]
  → cloud-init / setup_node / get_cpu_cores
  → return Node(enabled=True)

CloudProvisionerImpl.allocate
  → adapter.create_node → ip_addr
  → _setup_vm(ip_addr, ...)        [on success: session stays registered]
  → on CloudSetupError/Exception:
      machine_repository.disconnect(ip_addr)   ← NEW (Fix B1)
      adapter.delete_node(host=ip_addr)

allocate_task
  → _find_free_machines
      uow.tasks.list_by_status({RUNNING}) → busy_node_ips
      uow.nodes.list_enabled() → enabled_ips       ← NEW (Fix A)
      [s for s in repo.list_free(platforms)
       if s.ip in enabled_ips and s.ip not in busy_node_ips]
  → _allocate_free_machine
      for session in free_sessions:
        try: _try_start_on_machine(...)            ← NEW try/except (Fix C)
        except Exception: log.error; continue
      return False → falls through to cloud branch
```

## Specs to update

- `openspec/specs/cloud-provisioner` — new requirement: setup-failure
  disconnects `machine_repository` session (mid-run cleanup, extends the
  existing "stop closes connections" requirement).
- `openspec/specs/orchestrator` — invariant: allocatable ⇒ enabled in DB
  (free-machine query intersects `list_free` with enabled nodes).

No DB schema change. No CLI change. No public API change.

## Tests (unit, timing-aware fakes)

Fake `MachineRepository`: `connect` registers a session in `_sessions`
**before** DB-enable (mirrors `_setup_vm`). Fake `CloudProvisioner.allocate`:
flips the DB row to `enabled=TRUE` only on setup success.

Cases:
- A: multiple TO_DO + one pre-enable session → only post-enable session is
  selected (symptoms 1, 2 not reproducible after fix).
- B1: failed setup → `list_free` returns no stale session.
- C: stale/unreachable session in `free_sessions` → loop continues, cloud
  branch reached.
- D: cloud-init nonzero exit → error message contains `stdout=`.

## Open questions

None — all decisions made in explore.