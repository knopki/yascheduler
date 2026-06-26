# Explore Brief: fix-disconnect-bg-task-leak

## Problem

`SSHMachineGateway.disconnect(ip)` cancels **every** asyncio task in
`self._bg_tasks`, but that set holds occupancy monitors for **all** connected
machines, not just `ip`. Disconnecting one machine (e.g. an idle cloud node via
`deallocate_node`) silently kills occupancy monitoring for unrelated machines
that are still BUSY running tasks. The orchestrator never restarts those
monitors because `ip in self._occupancy_started` stays true, so the affected
machines are never released and their tasks are never consumed (outputs not
downloaded, status RUNNING forever).

## Rejected alternatives

- **B / B+ (set with attribute tag, or `dict[str, set[Task]]`)**: backwards
  compatible with existing `list(gateway._bg_tasks)` test idiom, but either
  relies on monkey-patching `asyncio.Task` attributes (B) or adds
  multi-task-per-IP machinery that has no current consumer (B+).
- **C (move lifecycle into orchestrator)**: cleaner separation but breaks the
  `MachineGateway.start_occupancy_check` port contract, propagating changes
  into the AiiDA plugin and protocol tests. Not justified by a one-line bug.
- **D (self-healing checker that exits when IP leaves `_machines`, drop
  explicit cancel)**: smallest patch, but loses prompt teardown of a checker
  that is mid-flight in a hung SSH call. Also leaves a stale iteration window.

## Selected approach — A

Replace `self._bg_tasks: set[asyncio.Task]` with
`self._bg_tasks: dict[str, asyncio.Task]`, keyed by machine IP. The invariant
"one occupancy monitor per IP" is already implied by the orchestrator's
`_occupancy_started: set[str]`; A makes it explicit at the gateway too.

- `start_occupancy_check(ip, config)` registers `self._bg_tasks[ip] = task`,
  replacing any prior monitor for that IP (idempotent on retry / reoccupy).
- `disconnect(ip)` pops only `self._bg_tasks[ip]` and cancels/awaits that one.
- `disconnect_all()` continues to iterate over `_machines` and call
  `disconnect(ip)` per machine — semantics preserved.

## Full labels / mapping tables

Touched data shape:

| Before                                       | After                                            |
| -------------------------------------------- | ------------------------------------------------ |
| `_bg_tasks: set[asyncio.Task]`               | `_bg_tasks: dict[str, asyncio.Task]` keyed by IP |
| `task.add_done_callback(self._bg_tasks.discard)` | `add_done_callback` removes entry by IP      |
| `disconnect`: cancel every task in set       | `disconnect`: pop + cancel only the IP's entry   |

Test idioms to migrate (callers reading the internal attribute):

- `tests/integration/test_ssh_gateway.py:516` — `list(gateway._bg_tasks)[0]`
- `tests/integration/test_ssh_gateway.py:628` — `bg_tasks = list(gateway._bg_tasks)`
- `tests/integration/test_ssh_gateway.py:662` — `bg_tasks = list(gateway._bg_tasks)`
- `tests/unit/test_ssh_gateway.py:856` — `task = list(gateway._bg_tasks)[0]`
- `tests/unit/test_ssh_gateway.py:887` — `await gateway.disconnect(ip)` (no
  direct indexing, but relies on the cancelled-gracefully behavior)

All switch to `gateway._bg_tasks[ip]`.

## Cross-module data flows

```
orchestrator._deallocator_consumer
  └─ deallocate_node(node)              [application/deallocate_nodes.py]
       └─ gateway.disconnect(node.ip)   [infra/ssh/gateway.py]
            ├─ _machines.pop(ip)
            └─ _bg_tasks.pop(ip).cancel()   ← AFTER FIX: was "cancel all"
```

```
orchestrator._task_consumer_consumer
  └─ if ip not in self._occupancy_started:
       gateway.start_occupancy_check(ip, engine)   ← registers _bg_tasks[ip]
       self._occupancy_started.add(ip)
```

## New regression test invariant

Multi-machine disconnect test (does not exist today):

1. `connect` machines A, B, C
2. `start_occupancy_check` on A, B, C → three entries in `_bg_tasks`
3. `await gateway.disconnect("B")`
4. assert `"A" in gateway._bg_tasks` and `"C" in gateway._bg_tasks`
5. assert monitors for A and C are still alive (not cancelled)
6. assert `"B" not in gateway._bg_tasks` and `"B" not in gateway._machines`

## Open questions

- None blocking. The orchestrator-side `_occupancy_started` accounting is left
  untouched; the bug root cause is entirely in the gateway. The orchestrator
  already correctly discards on consume and only adds on first-seen, so once
  the gateway stops cross-cancelling, the orchestrator flow self-corrects.
