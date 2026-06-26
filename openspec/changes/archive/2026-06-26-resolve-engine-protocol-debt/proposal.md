## Why

`OccupancyConfig` and `TaskExecutionEngine` Protocols in
`yascheduler/domain/ports.py` are orphaned leftovers. They were created by the
archived `gateway-port-cleanup` change (2026-06-21, design D7) because the
`domain.Engine` of that time lacked `check_cmd_code` / `sleep_interval` /
`deployable`, and `config.Engine` was unreachable from `domain` (layer
violation). After the archived `engine-to-domain-frozen` change (2026-06-25,
P2 / design D4), `Engine` moved to `yascheduler.domain`, became a frozen
dataclass carrying ALL of those fields, and `infra → domain` /
`application → domain` imports became R3-legal. D4 deleted the parallel
`PEngine` / `PEngineRepository` Protocols with the explicit rationale that
"Protocol duplication cost exceeds the segmentation benefit" for a
single-implementer case — but `OccupancyConfig` / `TaskExecutionEngine`, whose
rationale D4's move also invalidated, were left in place.

The visible cost: three production `cast()` workarounds
(`application/allocate_task.py:138,146` and
`application/orchestrator.py:352`) exist only because a frozen dataclass is not
statically assignable to a Protocol whose members mypy treats as settable. The
runtime value passed is always a concrete `Engine`; the Protocols never had a
second implementer. This change finishes the cleanup D4 started.

## What Changes

- Delete the `OccupancyConfig` Protocol class from `yascheduler/domain/ports.py`
  (and its `START_CONTRACT` / `END_CONTRACT` block).
- Delete the `TaskExecutionEngine` Protocol class from
  `yascheduler/domain/ports.py` (and its contract block).
- Replace every type annotation referencing `OccupancyConfig` or
  `TaskExecutionEngine` with the concrete `Engine` type from
  `yascheduler.domain.engine`:
  - `domain/ports.py`: `MachineGateway.start_occupancy_check(..config: Engine)`
    and `MachineGateway.start_task_on_machine(..engine: Engine)`; add
    `from .engine import Engine` to the existing `TYPE_CHECKING` block (no
    runtime cycle — `engine.py` imports only `.exceptions`).
  - `application/orchestrator.py` and `application/allocate_task.py`: imports
    and `Callable[..., TaskExecutionEngine, ...]` callback signatures
    (3 sites in `allocate_task.py`, 1 in `orchestrator.py`).
  - `infra/ssh/gateway.py`: runtime import `TaskExecutionEngine` → `Engine`;
    `TYPE_CHECKING` import `OccupancyConfig` → `Engine`; four method
    signatures (`_exec_spawn_command`, `start_task_on_machine`,
    `occupancy_check`, `start_occupancy_check`).
- Remove the three production `cast()` calls at `allocate_task.py:138,146` and
  `orchestrator.py:352`. After the parameter types become `Engine`, the casts
  are identity and the cast-bridged mismatch disappears. (The `cast` import
  in `allocate_task.py` and `orchestrator.py` becomes unused and is removed —
  `ruff check .` flags it.)
- Remove `OccupancyConfig` and `TaskExecutionEngine` from the
  `yascheduler.domain` public re-export: drop the two names from `__all__`,
  the `from .ports import (...)` block, and the `MODULE_MAP` descriptions in
  `domain/__init__.py`.
- Update `tests/unit/test_domain_ports.py`: drop the two Protocol imports, add
  `Engine`, and retype the two `StubMachineGateway` method signatures that
  referenced them (`start_occupancy_check(..config: Engine)`,
  `start_task_on_machine(..engine: Engine)`).
- Update GRACE-lite markup: `MODULE_CONTRACT` / `MODULE_MAP` in
  `domain/ports.py`, `domain/__init__.py`, and `infra/ssh/gateway.py` where
  they enumerate the deleted Protocols; remove the two `<annotations>` entries
  under `M-DOMAIN-PORTS` in `docs/knowledge-graph.xml`.
- Update the `domain-ports` capability spec: remove the requirements that
  mandate the `OccupancyConfig` and `TaskExecutionEngine` Protocol classes, and
  restate the `MachineGateway` occupancy/deployment method signatures in terms
  of `Engine`. Update the `cloud-config-protocol` capability spec to drop the
  now-stale "follows the precedent of `OccupancyConfig` and
  `TaskExecutionEngine`" sentence.

No behavioral change. The runtime values flowing through these signatures were
always `Engine` instances; only the static types and the three bridging casts
change.

## Capabilities

### New Capabilities
<!-- None. This is a cleanup, not a new capability. -->

### Modified Capabilities
- `domain-ports`: Remove the `OccupancyConfig` and `TaskExecutionEngine`
  Protocol requirements; restate `MachineGateway.start_occupancy_check` and
  `start_task_on_machine` signatures in terms of the concrete `Engine` type.
- `cloud-config-protocol`: Remove the stale precedent reference to
  `OccupancyConfig` / `TaskExecutionEngine` (the `CloudConfig` Protocol itself
  is unchanged and stays in place).

## Impact

- **Code**: 6 files edited
  (`domain/ports.py`, `domain/__init__.py`, `application/orchestrator.py`,
  `application/allocate_task.py`, `infra/ssh/gateway.py`,
  `tests/unit/test_domain_ports.py`); ~59 lines touched; 3 `cast()` calls and
  2 Protocol classes removed.
- **APIs**: `OccupancyConfig` and `TaskExecutionEngine` are removed from the
  `yascheduler.domain` facade. A repo-wide grep confirms no production or test
  consumer imports either name through `yascheduler.domain` except
  `tests/unit/test_domain_ports.py`, which this change updates. No CLI, INI,
  DB schema, or `Yascheduler` public API change. Per AGENTS.md the stable
  public surface is untouched.
- **Layers contract**: Unchanged. `infra → domain.Engine` and
  `application → domain.Engine` are already R3-legal (proven by the archived
  `engine-to-domain-frozen` D4). No new cross-layer import.
- **Dependencies**: None. No new or removed third-party packages.
- **Specs**: `domain-ports` capability spec updated (delta); `cloud-config-protocol`
  capability spec updated (delta, precedent-reference removal only).
- **Tests**: `tests/unit/test_domain_ports.py` updated (2 signature retypes +
  import swap). The `isinstance(stub, MachineGateway)` assertion stays green:
  `@runtime_checkable` Protocols check method presence, not parameter
  signature compatibility (PEP 544). `mock_pengine = MagicMock(spec=Engine)`
  in `tests/unit/test_ssh_gateway.py` and `tests/integration/test_ssh_gateway.py`
  already carries `spec=Engine` and passes an `Engine`-typed parameter without
  any `# type: ignore` — no change needed there.
- **Knowledge graph**: `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` loses the
  two `<annotations>` entries for the deleted Protocols. No `M-*` node added or
  removed; `M-DOMAIN-ENGINE` already exists and gains no new edge (it was
  already depended on by the application/infra consumers).
- **Verification**: `uv run pytest -m unit` passes;
  `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run lint-imports` clean; `python3 scripts/grace_check.py` passes;
  `openspec validate --all --json` passes after the spec deltas.