## Why

`SSHMachineGateway.disconnect(ip)` cancels every asyncio task in `self._bg_tasks`,
but that set holds the occupancy monitors for **all** connected machines. The
orchestrator deallocates idle cloud nodes routinely (`deallocate_node` →
`gateway.disconnect`); each call silently kills occupancy monitoring for every
other connected machine. Affected BUSY machines are never released (their
monitor is gone) and the orchestrator never restarts the monitor because
`ip in self._occupancy_started` remains true. Tasks on those machines stay in
`RUNNING` forever — outputs are never downloaded, completion is never recorded.
This hits any deployment that mixes a busy static node with autoscaled cloud
nodes.

## What Changes

- Re-key `SSHMachineGateway._bg_tasks` from `set[asyncio.Task]` to
  `dict[str, asyncio.Task]` keyed by machine IP, making the existing
  "one occupancy monitor per IP" invariant explicit at the gateway level.
- `start_occupancy_check(ip, config)` stores `self._bg_tasks[ip] = task`,
  overwriting any prior monitor for that IP (idempotent on reoccupy/retry).
- `disconnect(ip)` pops **only** `self._bg_tasks[ip]` and cancels/awaits that
  single task before closing the SSH connection. Other machines' monitors are
  untouched.
- `disconnect_all()` keeps iterating over `_machines` and calling
  `disconnect(ip)` per machine — observable behavior unchanged.
- `start_occupancy_check`'s done-callback is updated to remove the dict entry
  by IP instead of discarding from a set.
- Internal-attribute test idioms (`list(gateway._bg_tasks)[0]`,
  `list(gateway._bg_tasks)`) are migrated to `gateway._bg_tasks[ip]`.
- Add a multi-machine regression test asserting that disconnecting one IP
  leaves other IPs' occupancy monitors alive.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `ssh-gateway`: tighten the "Disconnect and cleanup" requirement so that
  `disconnect(ip)` is contractually scoped to that IP — it SHALL NOT cancel
  background tasks registered for any other machine. Adds a regression
  scenario covering the multi-machine invariant.

## Impact

- **Code**: `yascheduler/infra/ssh/gateway.py` (one data-structure change plus
  two call-site updates inside `disconnect` and `start_occupancy_check`). No
  changes to the `MachineGateway` Protocol, no signature changes, no public
  API impact.
- **Callers of `disconnect`**: `application/deallocate_nodes.py::deallocate_node`
  and `application/orchestrator.py::_deallocator_consumer` get the bug fix for
  free; no caller changes required.
- **Orchestrator accounting**: `Orchestrator._occupancy_started` accounting is
  unchanged — it was correct in isolation; the bug lived entirely in the
  gateway. Once the gateway stops cross-cancelling, the orchestrator's
  "first-seen add / consume-time discard" flow self-corrects.
- **Tests**: 4–5 existing tests index `gateway._bg_tasks` as a set; they move
  to dict-key access. One new multi-machine regression test is added to both
  unit and integration suites.
- **Dependencies / schema**: none. No DB migration, no config change, no
  AiiDA plugin impact.
- **Public surface**: none. `_bg_tasks` is a private attribute; the change is
  internal.
