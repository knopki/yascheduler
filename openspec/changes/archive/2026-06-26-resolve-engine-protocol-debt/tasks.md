## 1. domain/ports.py — delete Protocols, retype MachineGateway methods

- [x] 1.1 Add `from .engine import Engine` to the existing `TYPE_CHECKING` block in `yascheduler/domain/ports.py` (after the `from .model import (...)` block, around line 39). Confirm no runtime cycle (`engine.py` imports only `.exceptions`).
- [x] 1.2 Delete the `OccupancyConfig` Protocol class and its `START_CONTRACT: OccupancyConfig` / `END_CONTRACT: OccupancyConfig` block (lines ~96-113).
- [x] 1.3 Delete the `TaskExecutionEngine` Protocol class and its `START_CONTRACT: TaskExecutionEngine` / `END_CONTRACT: TaskExecutionEngine` block (lines ~116-135).
- [x] 1.4 Retype `MachineGateway.start_occupancy_check` signature: `config: OccupancyConfig` → `config: Engine` (line ~224).
- [x] 1.5 Retype `MachineGateway.start_task_on_machine` signature: `engine: TaskExecutionEngine` → `engine: Engine` (line ~229).
- [x] 1.6 Update the `START_MODULE_CONTRACT` / `START_MODULE_MAP` in `ports.py`: remove `OccupancyConfig` and `TaskExecutionEngine` from the SCOPE line and the exported-symbol descriptions (lines ~5, 13-14).

## 2. domain/__init__.py — remove from facade re-export

- [x] 2.1 Remove `OccupancyConfig` and `TaskExecutionEngine` from the `__all__` list (lines ~106-107).
- [x] 2.2 Remove `OccupancyConfig` and `TaskExecutionEngine` from the `from .ports import (...)` block (lines ~165-166).
- [x] 2.3 Remove the two `MODULE_MAP` entries describing `OccupancyConfig` and `TaskExecutionEngine` (lines ~48-49).
- [x] 2.4 Verify `grep -rn "OccupancyConfig\|TaskExecutionEngine" yascheduler/domain/` returns zero matches after 1.x and 2.x.

## 3. application/allocate_task.py — imports, callback sigs, remove casts

- [x] 3.1 Replace the `OccupancyConfig,` and `TaskExecutionEngine,` imports from `yascheduler.domain` (lines 37, 40) with `Engine,` (single import line; remove the two old names).
- [x] 3.2 Add `Engine` to the `TYPE_CHECKING` import block from `yascheduler.domain` (lines 49-54) if not already present at runtime — confirm whether `allocate_task.py` needs `Engine` at runtime or only under `TYPE_CHECKING` (it appears in `Callable[..., Engine, ...]` annotations only, so `TYPE_CHECKING` suffices given `from __future__ import annotations`).
- [x] 3.3 Retype the three `Callable[..., TaskExecutionEngine, ...]` annotations to `Callable[..., Engine, ...]` (lines 123, 200, 463).
- [x] 3.4 Remove `cast("TaskExecutionEngine", engine)` at line 138 — pass `engine` directly to `start_task_on_machine`.
- [x] 3.5 Remove `cast("OccupancyConfig", engine)` at line 146 — pass `engine` directly to `gateway.start_occupancy_check`.
- [x] 3.6 Remove the now-unused `cast` import from `from typing import TYPE_CHECKING, NamedTuple, cast` (line 32) — change to `from typing import TYPE_CHECKING, NamedTuple`.
- [x] 3.7 Remove/update the explanatory comment at lines 133-134 ("Engine is a frozen dataclass; the port Protocols...") since the Protocols no longer exist.
- [x] 3.8 Update the `START_CONTRACT: _try_start_on_machine` and `START_CONTRACT: _allocate_free_machine` INPUTS comments that reference `TaskExecutionEngine` (lines 109, 200) to reference `Engine`.

## 4. application/orchestrator.py — imports, method sig, remove cast

- [x] 4.1 Replace the `OccupancyConfig,` and `TaskExecutionEngine,` imports from `yascheduler.domain` (lines 37, 40) — remove `OccupancyConfig`; change `TaskExecutionEngine` to `Engine`. Confirm whether `Engine` is needed at runtime or under `TYPE_CHECKING` (used in `_start_task_on_machine` signature, so `TYPE_CHECKING` suffices given `from __future__ import annotations`; if `Engine` is already in the `TYPE_CHECKING` block, just remove the two old runtime imports).
- [x] 4.2 Retype `Orchestrator._start_task_on_machine` signature: `engine: TaskExecutionEngine` → `engine: Engine` (line 160).
- [x] 4.3 Remove `cast("OccupancyConfig", engine)` at line 352 — pass `engine` directly to `self._gateway.start_occupancy_check`.
- [x] 4.4 Remove the now-unused `cast` import (line 28) if no other `cast` call remains in `orchestrator.py` — grep `cast(` in the file first to confirm.
- [x] 4.5 Remove/update the explanatory comment at lines 348-351 ("Engine is a frozen dataclass; OccupancyConfig Protocol declares...") since the Protocol no longer exists.
- [x] 4.6 Update the `START_CONTRACT: Orchestrator._start_task_on_machine` INPUTS comment referencing `TaskExecutionEngine` (line 152) to reference `Engine`.

## 5. infra/ssh/gateway.py — imports, 4 method sigs, contracts

- [x] 5.1 Change the runtime import `TaskExecutionEngine` (line 51, in the `from yascheduler.domain import (...)` block) to `Engine`.
- [x] 5.2 Change the `TYPE_CHECKING` import `OccupancyConfig` (line 72, `from yascheduler.domain import EngineRepository, OccupancyConfig`) to `Engine` — resulting line: `from yascheduler.domain import Engine, EngineRepository` (only if `Engine` is not already imported at runtime; since 5.1 makes `Engine` a runtime import, this `TYPE_CHECKING` line can drop `OccupancyConfig` entirely and keep just `EngineRepository`, or be merged — pick the form that avoids a duplicate `Engine` import).
- [x] 5.3 Retype `SSHMachineGateway._exec_spawn_command` signature: `engine: TaskExecutionEngine` → `engine: Engine` (line 541) and its `START_CONTRACT` INPUTS comment (line 564).
- [x] 5.4 Retype `SSHMachineGateway.start_task_on_machine` signature: `engine: TaskExecutionEngine` → `engine: Engine` (line 576) and its `START_CONTRACT` INPUTS comment (line 564).
- [x] 5.5 Retype `SSHMachineGateway.occupancy_check` signature: `config: OccupancyConfig` → `config: Engine` (line 745) and its `START_CONTRACT` INPUTS comment (line 742).
- [x] 5.6 Retype `SSHMachineGateway.start_occupancy_check` signature: `config: OccupancyConfig` → `config: Engine` (line 770) and its `START_CONTRACT` INPUTS comment (line 766).
- [x] 5.7 Update the `MODULE_MAP` in `gateway.py` if it enumerates `TaskExecutionEngine` / `OccupancyConfig` references.

## 6. tests/unit/test_domain_ports.py — stub sigs + imports

- [x] 6.1 Remove `OccupancyConfig,` and `TaskExecutionEngine,` from the `from yascheduler.domain.ports import (...)` block (lines 38-39).
- [x] 6.2 Add `Engine` import: either `from yascheduler.domain import Engine` or add `Engine` to an existing `yascheduler.domain` import in the file (check the top imports around lines 20-33).
- [x] 6.3 Retype `StubMachineGateway.start_occupancy_check` signature: `config: OccupancyConfig` → `config: Engine` (line 181).
- [x] 6.4 Retype `StubMachineGateway.start_task_on_machine` signature: `engine: TaskExecutionEngine` → `engine: Engine` (line 187).
- [x] 6.5 Run `uv run pytest -m unit tests/unit/test_domain_ports.py -q` — confirm `test_machine_gateway_protocol` still passes (PEP 544: `@runtime_checkable` checks method presence, not signature compatibility).

## 7. docs/knowledge-graph.xml — M-DOMAIN-PORTS annotations

- [x] 7.1 Open `docs/knowledge-graph.xml`, locate the `M-DOMAIN-PORTS` element, and remove the `<fn-...>` / `<type-...>` / `<class-...>` annotation entries for `OccupancyConfig` and `TaskExecutionEngine` (whichever prefix they use). Leave `CloudConfig`, `MachineGateway`, `CloudProvisioner`, `TaskRepository`, `NodeRepository` annotations intact.
- [x] 7.2 Confirm no other `M-*` node in the graph references `OccupancyConfig` or `TaskExecutionEngine` in its `<depends>` or `<CrossLink>` — grep the file. If any cross-link mentions them, update it.

## 8. Static checks + GRACE-lite validation

- [x] 8.1 Run `uv run ruff check .` — clean (expect the unused-`cast` imports to be flagged if 3.6/4.4 were missed; fix if so).
- [x] 8.2 Run `uv run ruff format --check .` — clean.
- [x] 8.3 Run `uv run lint-imports` — clean (R3 layers: `infra → domain.Engine` and `application → domain.Engine` already legal).
- [x] 8.4 Run `uv run zuban check` — clean (the 3 `cast()` sites and their `# type: ignore`-adjacent lines are gone; no new type errors).
- [x] 8.5 Run `python3 scripts/grace_check.py` — exit 0 (MODULE_CONTRACT / MODULE_MAP / CHANGE_SUMMARY consistent after the 1.6, 2.3, 5.7, 7.1 edits).
- [x] 8.6 Run `openspec validate --all --json` — passes after the spec deltas (section 9).

## 9. Spec deltas (already created — verify only)

- [x] 9.1 Confirm `openspec/changes/resolve-engine-protocol-debt/specs/domain-ports/spec.md` exists with MODIFIED MachineGateway port + REMOVED OccupancyConfig + REMOVED TaskExecutionEngine.
- [x] 9.2 Confirm `openspec/changes/resolve-engine-protocol-debt/specs/cloud-config-protocol/spec.md` exists with MODIFIED CloudConfig structural Protocol (precedent sentence replaced; all 6 original scenarios preserved).
- [x] 9.3 Run `openspec validate --all --json` — passes (this duplicates 8.6 but is the spec-specific gate).

## 10. Full test sweep + CHANGE_SUMMARY

- [x] 10.1 Run `uv run pytest -m unit` — all green (focus on `test_domain_ports.py`, `test_ssh_gateway.py` occupancy tests using `mock_pengine = MagicMock(spec=Engine)`, `test_application_orchestrator.py`, `test_application_use_cases.py`, `test_allocate_task_failure_modes.py`).
- [x] 10.2 Run `uv run pytest -m integration` if any integration test references the occupancy/start_task signatures (`tests/integration/test_ssh_gateway.py:301` uses `MagicMock(spec=Engine)` — confirm it still passes).
- [x] 10.3 Add/refresh `START_CHANGE_SUMMARY` `LAST_CHANGE` entries in the 5 edited source files (`domain/ports.py`, `domain/__init__.py`, `application/allocate_task.py`, `application/orchestrator.py`, `infra/ssh/gateway.py`) noting the Protocol deletion and Engine retype.
- [x] 10.4 Final grep: `grep -rn "OccupancyConfig\|TaskExecutionEngine" yascheduler/ tests/` returns zero matches (only historical mentions in `CHANGE_SUMMARY` / archived spec history are acceptable, and there should be none of those either since these names were never in a shipped archive spec).