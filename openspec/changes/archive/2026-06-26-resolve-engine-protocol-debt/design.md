## Context

`yascheduler/domain/ports.py` defines two structural Protocols —
`OccupancyConfig` and `TaskExecutionEngine` — that were introduced by the
archived `gateway-port-cleanup` change (design D7, 2026-06-21). D7 created them
because the `domain.Engine` of that time lacked `check_cmd_code`,
`sleep_interval`, and `deployable`, while `config.Engine` (which had them)
could not be imported from `domain` without a layer violation. The Protocols
captured the minimal field subset the SSH gateway reads for occupancy checks
and task deployment, and `config.Engine` satisfied them structurally.

The archived `engine-to-domain-frozen` change (P2, design D4, 2026-06-25)
relocated `Engine` to `yascheduler.domain.engine` as a frozen dataclass
carrying all of those fields, made `infra → domain` and
`application → domain` imports R3-legal, and deleted the parallel
`PEngine` / `PEngineRepository` Protocols with the rationale:

> "Protocol duplication cost exceeds the segmentation benefit" for a
> single-implementer case.

D4 did not touch `OccupancyConfig` / `TaskExecutionEngine`, leaving them as
orphan contracts whose original rationale D4's move invalidated. The visible
symptom: three production `cast()` calls
(`allocate_task.py:138`, `allocate_task.py:146`, `orchestrator.py:352`) bridge
the frozen `Engine` dataclass into the (implicitly settable) Protocol
annotations, because mypy does not consider a frozen dataclass statically
assignable to a Protocol with settable members.

Constraints carried forward:
- R3 layers contract (`entrypoints → infra → application → domain → shared`).
  After this change, `infra → domain.Engine` and `application → domain.Engine`
  remain R3-legal (already proven by D4). No new cross-layer edge.
- GRACE-lite: `domain/ports.py`, `domain/__init__.py`, and
  `infra/ssh/gateway.py` carry `MODULE_CONTRACT` / `MODULE_MAP` / function
  contracts that enumerate the deleted Protocols; `docs/knowledge-graph.xml`
  `M-DOMAIN-PORTS` carries `<annotations>` for both. All must be updated in the
  same change.
- Public interface stability (AGENTS.md): `OccupancyConfig` and
  `TaskExecutionEngine` are not part of the stable public surface (CLI, INI,
  DB schema, `Yascheduler` API, AiiDA entrypoint). They are internal domain
  ports. A repo-wide grep confirms no consumer imports them through
  `yascheduler.domain` except `tests/unit/test_domain_ports.py`, which this
  change updates.

## Goals / Non-Goals

**Goals:**
- Delete the `OccupancyConfig` and `TaskExecutionEngine` Protocol classes from
  `yascheduler/domain/ports.py`.
- Replace every annotation referencing them with the concrete `Engine` type
  from `yascheduler.domain.engine`, across `domain/ports.py`,
  `application/orchestrator.py`, `application/allocate_task.py`,
  `infra/ssh/gateway.py`, and `tests/unit/test_domain_ports.py`.
- Remove the three production `cast()` calls that existed only to bridge
  frozen-`Engine` to settable-Protocol, and remove the now-unused `cast`
  import in the two application files.
- Remove both names from the `yascheduler.domain` public re-export
  (`__all__`, `from .ports import (...)`, `MODULE_MAP`).
- Update the `domain-ports` and `cloud-config-protocol` capability spec
  deltas, the GRACE-lite module contracts/maps, and the
  `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` annotations.

**Non-Goals:**
- Do NOT touch the `CloudConfig` Protocol. Its rationale (multiple `ConfigCloud*`
  DTOs, `Sequence` invariance) is a separate root and is explicitly excluded.
- Do NOT touch the `MachineGateway`, `CloudProvisioner`, `TaskRepository`, or
  `NodeRepository` Protocols. These have real polymorphism (SSH + Stub +
  `MagicMock` in tests) and are not single-implementer duplications.
- Do NOT change the `Engine` dataclass itself (no field additions/removals,
  no mutability change).
- Do NOT introduce a read-only-Protocol variant (`@property`-based) — that
  preserves the duplication D4 rejected (rejected alternative V1).
- Do NOT change any runtime behavior. The values passed through these
  signatures were always `Engine` instances; only static types and bridging
  casts change.
- Do NOT migrate the remaining type-suppression groups (B, C, D, E, F, G, H, I
  from the exploration). Each is a separate change proposal.

## Decisions

### D1: Delete the Protocols; type annotations use the concrete `Engine`

Replace `OccupancyConfig` and `TaskExecutionEngine` with `Engine` in every
signature they appear in. `Engine` is a frozen dataclass in
`yascheduler.domain.engine` and already carries all fields both Protocols
declared (`name`, `check_pname`, `check_cmd`, `check_cmd_code`,
`sleep_interval`, plus `spawn`, `input_files`).

**Rationale**: This finishes the D4 cleanup. D4 established the project's
position that a Protocol mirroring a single concrete class is duplication whose
cost exceeds the Interface-Segregation benefit. `OccupancyConfig` /
`TaskExecutionEngine` are exactly that case post-D4.

**Alternatives considered**:
- *V1 — read-only Protocol via `@property`*: removes the casts but preserves
  the duplication D4 rejected and grows boilerplate (+7 properties across two
  Protocols). Inconsistent with the D4 precedent. Rejected.
- *V2 — rely on a mypy quirk to treat Protocol attributes as read-only without
  `@property`*: fragile, mypy-version-dependent. Rejected.
- *V4 — keep the casts, document them as the price of the design*: leaves 3
  perpetual `cast()` debt lines and hides regressions from reviewers.
  Rejected.

### D2: Import `Engine` in `ports.py` under `TYPE_CHECKING`

`domain/ports.py` already uses `from __future__ import annotations` and a
`TYPE_CHECKING` block importing `ConnectedMachine`, `Node`, `ProcessResult`,
`Task`, `TaskStatus` from `.model`. Add `from .engine import Engine` to that
same block.

**Rationale**: No runtime import cycle. `domain/engine.py` imports only
`from .exceptions import MissingInputFileError` (verified by grep). Adding
`Engine` to the `TYPE_CHECKING` block keeps `ports.py` runtime-import-light
and matches the existing pattern for domain type imports in that file.

### D3: Update `MachineGateway` Protocol method signatures

Two `MachineGateway` methods reference the deleted Protocols:
- `start_occupancy_check(ip: str, config: OccupancyConfig) -> None` becomes
  `start_occupancy_check(ip: str, config: Engine) -> None`.
- `start_task_on_machine(machine: ConnectedMachine, engine: TaskExecutionEngine,
  task: Task, ncpus: int, engines_dir: PurePath) -> bool` becomes
  `start_task_on_machine(machine: ConnectedMachine, engine: Engine, task: Task,
  ncpus: int, engines_dir: PurePath) -> bool`.

**Rationale**: The `MachineGateway` Protocol stays (it has real polymorphism);
only the parameter types of two of its methods change to the concrete `Engine`
that was always the runtime value.

### D4: Remove the three production `cast()` calls and the now-unused `cast` import

- `application/allocate_task.py:138` `cast("TaskExecutionEngine", engine)` →
  `engine`.
- `application/allocate_task.py:146` `cast("OccupancyConfig", engine)` →
  `engine`.
- `application/orchestrator.py:352` `cast("OccupancyConfig", engine)` →
  `engine`.

After the parameter types become `Engine`, the casts are identity. The `cast`
import in `allocate_task.py` (line 32) and `orchestrator.py` (line 28) becomes
unused and is removed (`ruff check .` flags unused imports).

**Rationale**: The casts existed solely to bridge frozen-`Engine` to
settable-Protocol. With the Protocol gone, the bridge is unnecessary.

### D5: Remove the names from the `yascheduler.domain` facade

`domain/__init__.py` re-exports both Protocols via `__all__`, the
`from .ports import (...)` block, and the `MODULE_MAP` descriptions. Remove
all three. The `CloudConfig`, `CloudProvisioner`, `MachineGateway`,
`NodeRepository`, `TaskRepository` re-exports stay unchanged.

**Rationale**: The names no longer exist in `ports.py`; re-exporting them
would be a broken import. Grep confirms no external consumer imports them
through the facade except `tests/unit/test_domain_ports.py`, which this change
updates.

### D6: Keep `MachineGateway` `@runtime_checkable`; `isinstance` assertion stays green

`tests/unit/test_domain_ports.py::test_machine_gateway_protocol` asserts
`isinstance(StubMachineGateway(), MachineGateway)`. The stub's
`start_occupancy_check` and `start_task_on_machine` signatures are retyped
from `OccupancyConfig` / `TaskExecutionEngine` to `Engine`.

**Rationale**: PEP 544 specifies that `@runtime_checkable` Protocol
`isinstance` checks verify method presence, not parameter signature
compatibility. The stub still defines both methods; the assertion stays green
regardless of the parameter type annotations.

### D7: Update `infra/ssh/gateway.py` runtime + `TYPE_CHECKING` imports

`gateway.py:51` runtime-imports `TaskExecutionEngine` from
`yascheduler.domain`; `gateway.py:72` `TYPE_CHECKING`-imports
`OccupancyConfig`. Both become `Engine`. The four method signatures
(`_exec_spawn_command`, `start_task_on_machine`, `occupancy_check`,
`start_occupancy_check`) and their `START_CONTRACT` / `END_CONTRACT` blocks
are retyped.

**Rationale**: `infra → domain.Engine` is R3-legal (D4). The runtime import of
`Engine` is required because `gateway.py` uses it in actual function signatures
evaluated by type checkers (and `from __future__ import annotations` is in
effect, but `Engine` is also referenced in contract comments that should match
the signatures).

### D8: Spec deltas — `domain-ports` MODIFIED, `cloud-config-protocol` MODIFIED

`domain-ports` capability: the `MachineGateway port` requirement is MODIFIED —
the two method signatures change from `OccupancyConfig`/`TaskExecutionEngine`
to `Engine`, and the standalone `OccupancyConfig` / `TaskExecutionEngine`
Protocol requirements are removed. The `CloudConfig` requirement text in
`domain-ports` also drops the "follows the precedent of `OccupancyConfig` and
`TaskExecutionEngine`" sentence.

`cloud-config-protocol` capability: the `CloudConfig` structural Protocol
requirement is MODIFIED only to remove the stale precedent-reference sentence
(the `CloudConfig` Protocol itself stays).

**Rationale**: Specs must reflect the codebase after the change (AGENTS.md
OpenSpec rule). The `domain-ports` spec currently mandates the deleted
Protocols as SHALL requirements; those MUST be removed. The
`cloud-config-protocol` spec references the deleted Protocols as precedent;
that reference MUST be dropped so it does not point at non-existent code.

## Risks / Trade-offs

- **[Future second `Engine`-shaped type appears]** → If a second engine record
  type is ever introduced (e.g., a remote-configured engine variant), the
  deleted Protocols would need to be reintroduced or a shared base class added.
  *Mitigation*: YAGNI — no such type is planned. If one appears, reintroducing
  a Protocol at that point is the standard response to new polymorphism and is
  no harder than keeping the current Protocols would have been. The change is
  reversible.

- **[`isinstance(stub, MachineGateway)` regresses]** → *Mitigation*: PEP 544
  guarantees `@runtime_checkable` checks method presence, not signature
  compatibility. Verified: the stub keeps both methods. The existing
  `test_machine_gateway_protocol` test is the canary.

- **[Public API break for downstream consumers importing the Protocols]** →
  *Mitigation*: repo-wide grep confirms no consumer imports
  `OccupancyConfig` / `TaskExecutionEngine` through `yascheduler.domain`
  except `tests/unit/test_domain_ports.py`, which the change updates. The
  names are not part of the AGENTS.md stable public surface.

- **[GRACE-lite / knowledge-graph drift]** → *Mitigation*: the change updates
  `MODULE_CONTRACT` / `MODULE_MAP` in `domain/ports.py`,
  `domain/__init__.py`, `infra/ssh/gateway.py`, and the `M-DOMAIN-PORTS`
  `<annotations>` in `docs/knowledge-graph.xml` in the same change.
  `python3 scripts/grace_check.py` is run before completion.

- **[Unused `cast` import left behind]** → *Mitigation*: explicitly called out
  in D4; `ruff check .` flags unused imports and the implementer removes them.

## Migration Plan

This is a pure cleanup with no runtime behavior change, no schema change, no
config change, and no API change to the stable public surface. There is no
data to migrate and no rollout ordering.

Sequence:
1. Edit `domain/ports.py` (delete the two Protocol classes, add `Engine` to
   `TYPE_CHECKING`, retype two `MachineGateway` methods).
2. Edit `domain/__init__.py` (remove the two names from `__all__`, the
   `from .ports import (...)` block, and `MODULE_MAP`).
3. Edit `application/allocate_task.py` (imports, 3 callback signatures, remove
   2 casts, remove unused `cast` import, update contract comments).
4. Edit `application/orchestrator.py` (imports, 1 method signature, remove 1
   cast, remove unused `cast` import, update contract comments).
5. Edit `infra/ssh/gateway.py` (runtime + `TYPE_CHECKING` imports, 4 method
   signatures, 4 contract blocks).
6. Edit `tests/unit/test_domain_ports.py` (imports, 2 stub method signatures).
7. Update `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` `<annotations>`.
8. Update spec deltas (`domain-ports`, `cloud-config-protocol`).
9. Run `uv run pytest -m unit`, `uv run zuban check`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run lint-imports`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.

Rollback: `git revert` the change commit. No partial state is persistent
because the change is type-annotation-only with no data or config effects.

## Open Questions

None. All decisions are settled by the explore-brief analysis and the D4
precedent.