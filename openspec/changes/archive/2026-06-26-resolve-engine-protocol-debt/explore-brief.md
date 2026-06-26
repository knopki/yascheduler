# Explore Brief: resolve-engine-protocol-debt

## Problem

`OccupancyConfig` and `TaskExecutionEngine` Protocols in
`yascheduler/domain/ports.py` are orphaned leftovers with an outdated
rationale. They were created by `gateway-port-cleanup` (2026-06-21, D7) because
`domain.Engine` at the time lacked `check_cmd_code`/`sleep_interval`/`deployable`
and `config.Engine` was unreachable from `domain` (layer violation). After
`engine-to-domain-frozen` (2026-06-25, P2/D4), `Engine` moved to
`yascheduler.domain`, became a frozen dataclass with ALL those fields, and
`infra → domain` / `application → domain` imports became R3-legal.

D4 deleted the parallel `PEngine`/`PEngineRepository` Protocols with the
explicit rationale: *"Protocol duplication cost > segmentation benefit"* for a
single-implementer case. But `OccupancyConfig`/`TaskExecutionEngine` — created
for the same kind of reason that D4 invalidated — were not cleaned up. The
result is 3 `cast()` workarounds in production
(`allocate_task.py:138,146`, `orchestrator.py:352`) because a frozen dataclass
is not statically assignable to a Protocol with (implicitly) settable members.

## Rejected alternatives

- **V1 — read-only Protocol via `@property`**: would remove the casts and keep
  the Protocols, but preserves duplication that D4 already rejected. Boilerplate
  grows (+7 properties). Inconsistent with D4 precedent. Rejected.
- **V2 — rely on a mypy quirk to treat Protocol attrs as read-only**: fragile,
  mypy-version-dependent. Rejected.
- **V4 — keep the casts, document them as "price of design"**: leaves 3
  perpetual cast() debt lines; the casts hide real regressions from reviewers.
  Rejected.

## Chosen approach: V3 — finish the D4 cleanup

Delete `OccupancyConfig` and `TaskExecutionEngine` Protocol classes. Replace
every type annotation referencing them with `Engine` (the concrete frozen
dataclass in `yascheduler.domain.engine`). Remove the 3 production `cast()`
calls that existed only to bridge frozen-Engine to settable-Protocol.

This is not a new architectural choice — it is the direct continuation of D4
(`engine-to-domain-frozen`) for the two Protocols that D4's rationale also
covers but did not touch.

## Full call-site map (audited)

### Production (`yascheduler/`)

| File | Site | Action |
|------|------|--------|
| `domain/ports.py:101` | `class OccupancyConfig(Protocol)` | DELETE class + contract |
| `domain/ports.py:121` | `class TaskExecutionEngine(Protocol)` | DELETE class + contract |
| `domain/ports.py:224` | `MachineGateway.start_occupancy_check(..config: OccupancyConfig)` | → `config: Engine` |
| `domain/ports.py:229` | `MachineGateway.start_task_on_machine(..engine: TaskExecutionEngine)` | → `engine: Engine` |
| `domain/ports.py:33` | `TYPE_CHECKING` block | add `from .engine import Engine` |
| `domain/__init__.py:48-49` | MODULE_MAP | remove 2 entries |
| `domain/__init__.py:106-107` | `__all__` | remove 2 names |
| `domain/__init__.py:165-166` | `from .ports import (...)` | remove 2 names |
| `application/orchestrator.py:37,40` | imports | `OccupancyConfig` removed; `TaskExecutionEngine` → `Engine` |
| `application/orchestrator.py:160` | `_start_task_on_machine(..engine: TaskExecutionEngine)` | → `engine: Engine` |
| `application/orchestrator.py:352` | `cast("OccupancyConfig", engine)` | REMOVE cast → `engine` |
| `application/allocate_task.py:37,40` | imports | → `Engine` |
| `application/allocate_task.py:123,200,463` | 3× `Callable[..., TaskExecutionEngine, ...]` | → `Engine` |
| `application/allocate_task.py:138` | `cast("TaskExecutionEngine", engine)` | REMOVE cast |
| `application/allocate_task.py:146` | `cast("OccupancyConfig", engine)` | REMOVE cast |
| `infra/ssh/gateway.py:51` | runtime import `TaskExecutionEngine` | → `Engine` |
| `infra/ssh/gateway.py:72` | `TYPE_CHECKING` import `OccupancyConfig` | → `Engine` |
| `infra/ssh/gateway.py:541,576` | `_exec_spawn_command` / `start_task_on_machine` sigs | → `engine: Engine` |
| `infra/ssh/gateway.py:745,770` | `occupancy_check` / `start_occupancy_check` sigs | → `config: Engine` |

### Tests (`tests/`)

| File | Site | Action |
|------|------|--------|
| `tests/unit/test_domain_ports.py:38-39` | `from .ports import OccupancyConfig, TaskExecutionEngine` | remove; add `from yascheduler.domain import Engine` |
| `tests/unit/test_domain_ports.py:181` | `StubMachineGateway.start_occupancy_check(..config: OccupancyConfig)` | → `config: Engine` |
| `tests/unit/test_domain_ports.py:187` | `StubMachineGateway.start_task_on_machine(..engine: TaskExecutionEngine)` | → `engine: Engine` |

### NOT touched (intentionally)

- `CloudConfig` Protocol — different root (`Sequence` invariance, multiple
  DTOs). Separate scope.
- `MachineGateway` / `CloudProvisioner` / `TaskRepository` / `NodeRepository`
  Protocols — real polymorphism (SSH + Stub + MagicMock in tests). Keep.
- `tests/unit/test_ssh_gateway.py:230` `mock_pengine = MagicMock(spec=Engine)` —
  already typed as `Engine`; passes `Engine`-typed params without `# type: ignore`.
- `tests/integration/test_ssh_gateway.py:301` `MagicMock(spec=Engine)` — same.

## Cross-module data flow

```
allocate_task (Engine param)
   ├── _try_start_on_machine: start_task_on_machine(machine, engine, task)
   │     └── gateway.start_task_on_machine(machine, engine, task, ...)
   │           └── _exec_spawn_command(machine, engine, task, ...)  [reads engine.spawn]
   └── gateway.start_occupancy_check(ip, engine)
         └── occupancy_check(ip, engine)  [reads engine.check_pname / check_cmd]

orchestrator._start_task_on_machine(machine, engine, task)
   └── gateway.start_task_on_machine(machine, engine, task, ...)

orchestrator._task_consumer: gateway.start_occupancy_check(ip, engine)
```

`Engine` flows top-down from `EngineRepository` lookup → application use cases →
gateway. No construction of `OccupancyConfig`/`TaskExecutionEngine` ever
happened — `Engine` was always the concrete runtime value, cast only to satisfy
the type checker.

## Open questions

1. Does any `openspec/specs/` capability spec reference `OccupancyConfig` or
   `TaskExecutionEngine` as mandatory Protocols? — To check during proposal
   creation. Likely yes (gateway-port-cleanup created `domain-ports` spec
   entries); the change must update those spec requirements.
2. `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` annotations list both Protocols —
   must be removed in the same change (GRACE-lite rule).
3. Module contracts (`START_MODULE_CONTRACT` / `START_MODULE_MAP`) in
   `domain/ports.py`, `domain/__init__.py`, `infra/ssh/gateway.py` mention the
   Protocols — must be updated (GRACE-lite rule).

## Risk assessment

- **No import cycle**: `engine.py` imports only `.exceptions`; `ports.py` will
  import `Engine` under `TYPE_CHECKING` (file already uses
  `from __future__ import annotations`).
- **No `isinstance` regression**: `@runtime_checkable` Protocol checks method
  presence, not signature compatibility (PEP 544). `StubMachineGateway` still
  passes `isinstance(stub, MachineGateway)`.
- **No public API break**: grep confirmed no consumer imports
  `OccupancyConfig`/`TaskExecutionEngine` through `yascheduler.domain` except
  `test_domain_ports.py`, which the change updates.
- **R3 layers**: `infra → domain.Engine` and `application → domain.Engine` are
  already legal (proven by D4).