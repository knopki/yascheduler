## Context

`SSHMachineGateway` (`yascheduler/infra/ssh/gateway.py`) tracks two structures
per connected machine:

- `self._machines: dict[str, _MachineState]` — keyed by IP, the registry of
  live SSH connections and domain state.
- `self._bg_tasks: set[asyncio.Task]` — populated **only** by
  `start_occupancy_check` (one occupancy monitor per machine), with
  `task.add_done_callback(self._bg_tasks.discard)` for self-cleanup.

`disconnect(ip)` correctly pops the single `_machines[ip]` entry but then
iterates over the **entire** `_bg_tasks` set calling `task.cancel()`:

```python
for task in list(self._bg_tasks):
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
```

Net effect: disconnecting any one machine tears down occupancy monitoring for
every connected machine. The orchestrator's `_task_consumer_consumer` only
(re)starts occupancy when `ip not in self._occupancy_started`; the entry is
still there for the collateral victims, so the monitors are never recreated
and BUSY machines stay BUSY. Tasks in `RUNNING` never reach the consumer's
FREE branch → outputs are never downloaded → statuses never advance.

The trigger is routine: `Orchestrator._deallocator_consumer → deallocate_node
→ gateway.disconnect(ip)` fires on every idle-cloud-node teardown. Any
deployment mixing static and autoscaled nodes is exposed whenever a cloud
node is reclaimed while a static node is mid-task.

## Goals / Non-Goals

**Goals:**
- Disconnect (and only disconnect) the targeted IP's occupancy monitor.
- Preserve prompt teardown semantics: cancelling a monitor that is mid-flight
  in a hung SSH call must still happen during `disconnect`.
- Make the "one monitor per IP" invariant locally enforceable by the gateway's
  data structure, not just an implicit contract held by the orchestrator.
- Keep the public `MachineGateway` Protocol, all method signatures, and the
  AiiDA-facing surface byte-for-byte identical.

**Non-Goals:**
- Refactoring occupancy lifecycle into the orchestrator (Option C from the
  exploration). The port contract stays on the gateway.
- Supporting multiple concurrent occupancy monitors per IP. Today's contract
  is 1:1; if that ever changes, migrating `dict[str, asyncio.Task]` →
  `dict[str, set[asyncio.Task]]` is mechanical.
- Touching `Orchestrator._occupancy_started`. It was correct; the bug lived in
  the gateway.
- Changing connection close/wait_closed behavior in `disconnect`.

## Decisions

### Decision 1: Key `_bg_tasks` by IP (`dict[str, asyncio.Task]`)

**Choice**: replace the set with a dict keyed by the same IP namespace as
`_machines`.

**Rationale**:
- The 1:1 IP→monitor invariant is already implied by
  `Orchestrator._occupancy_started: set[str]` and by `start_occupancy_check`
  being called once per task allocation. Making the gateway enforce it locally
  turns a hidden contract into a structural one.
- O(1) lookup on both registration and disconnect; no linear scan.
- `disconnect(ip)` becomes a mirror of `_machines.pop(ip)`: one registry, one
  background task, both keyed identically.

**Alternatives considered**:
- **B** — keep `set[asyncio.Task]`, attach `task._ip = ip` as an attribute,
  filter on disconnect. Rejected: monkey-patching asyncio.Task is fragile and
  loses the structural guarantee (a future caller could still insert a task
  without tagging it).
- **B+** — `dict[str, set[asyncio.Task]]` for future multi-monitor-per-IP.
  Rejected as YAGNI: no current or planned second producer of bg tasks.
- **C** — move occupancy lifecycle into the orchestrator (gateway becomes
  stateless for bg). Rejected: breaks `MachineGateway.start_occupancy_check`
  port contract, propagates to AiiDA plugin and protocol stubs.
- **D** — drop explicit cancel; make `_checker` exit when `ip not in
  _machines`. Rejected: loses prompt teardown of monitors stuck in a hung SSH
  call (would only unwind on the next `asyncio.wait_for` timeout cycle), and
  makes `disconnect` no longer mean "monitor is stopped".

### Decision 2: Done-callback removes the IP entry, not the task object

```python
def _on_done(_t: asyncio.Task) -> None:
    # Only remove if it's still us; a re-registered replacement must survive.
    if self._bg_tasks.get(ip) is _t:
        self._bg_tasks.pop(ip, None)
```

**Rationale**: with `dict[str, ...]`, an IP can be re-registered (idempotent
reoccupy). If the older task's done-callback fired after a newer task was
already installed for the same IP, naive `pop(ip)` would evict the live
monitor. The identity check (`get(ip) is _t`) preserves the replacement.

### Decision 3: `disconnect(ip)` pops the entry before awaiting cancellation

```python
state = self._machines.pop(ip, None)
if state is None:
    return
task = self._bg_tasks.pop(ip, None)
if task is not None:
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
# ... close conn as today
```

**Rationale**: pop-then-cancel matches the `_machines.pop` semantics already
present and prevents any re-entry race from re-inserting the cancelled task
into the dict during `await`.

### Decision 4: `disconnect_all()` unchanged

It already iterates `list(self._machines)` and calls `disconnect(ip)` per
machine. With Decision 1, each per-IP disconnect now correctly cancels only
that IP's monitor, so the aggregate result (everything torn down) is
preserved.

## Risks / Trade-offs

- **Risk**: existing tests reach into `gateway._bg_tasks` as a set
  (`list(gateway._bg_tasks)[0]`, `len(gateway._bg_tasks)`).
  → **Mitigation**: migrate the ~4 affected test sites to `gateway._bg_tasks[ip]`
  in the same change. Listed explicitly in tasks.
- **Risk**: a caller outside the orchestrator relies on cancelling all bg
  tasks via `disconnect` (undocumented side effect).
  → **Mitigation**: audited call sites — `disconnect` is only invoked from
  `deallocate_node`, `disconnect_all`, the CLI `manage-node` flow, and
  `check_status`. None rely on collateral cancellation. The new
  multi-machine regression test pins the intended semantics.
- **Trade-off**: dict introduces a tiny bit more bookkeeping than a set
  (IP-keyed insertion, identity-checked removal). Justified by the structural
  invariant and the bug class it closes.
- **Risk**: identity-check in the done-callback could mask a leak if a task
  is somehow replaced without the old one being cancelled.
  → **Mitigation**: `start_occupancy_check` is the only inserter; on
  re-registration it should cancel the prior task explicitly (added to the
  implementation contract).

## Migration Plan

- Single-PR change; no schema, config, protocol, or AiiDA-facing delta.
- Deploy: standard `uv sync` + daemon restart. No DB migration.
- Rollback: revert the single commit; behaviour returns to the
  buggy-but-pre-existing set semantics. No persisted state is affected.
- Observability: structured log line
  `[SSHGateway][disconnect][CANCEL_BG] ip=%s` added at the cancellation site
  so operators can confirm scope on the next deallocate cycle.
- **Preventive, not curative**: this fix stops new cross-cancellations from
  happening. Machines whose monitors were already killed before the deploy
  remain stuck (their `ip ∈ _occupancy_started` with a dead monitor blocks
  both restart and consume in the orchestrator). Operators deploying to a
  running daemon with stuck victims should restart the daemon (or otherwise
  re-trigger the affected tasks) to recover them.
