## Why

The spec suite (~4500 lines across 20 capabilities) has accreted content that
does not belong in behavioral specifications:

1. **Stale contradictions** — `testing-unit` still asserts a 5-key dict shape
   with `ip`, `e2e-testing` references the removed `YaLogger.trace()` and the
   removed `M-APPLICATION-ALLOCATE` logger namespace, `test-db-integration`
   uses removed repository method names (`add`, `get_by_ips`, `has_node`,
   `set_task_error`), and `package-facades`'s `node.ip` contradicts the
   `Node.hostname` field defined by `domain-entities`. The suite validates
   `green` but encodes behavior the production code no longer exhibits.
2. **Shape passed off as behavior** — value-object field lists, dataclass
   default values, function signatures, exception message format strings, SQL
   file inventories, enum value lists, and `pyproject.toml` keys are
   restated as Requirements. These are type definitions and config — they
   belong in code-level GRACE contracts (`MODULE_CONTRACT` SCOPE/KEYWORDS,
   `CLASS_*` INVARIANTS/ENSURES, `FUNC_*`/`METHOD_*` PURPOSE+ENSURES), not in
   spec scenarios. When the shape changes, the spec drifts silently because
   nothing structural binds it to the code.
3. **Duplication** — `package-facades` R1/R2/R3 each re-pins the same rule
   via dozens of per-symbol scenarios (a single `import-linter` contract is
   the actual guard); `materialize_task` / `TaskCreated` emission is described
   in four capabilities; the jump-host stamping rule is restated in five
   places; the logging-discipline guard appears in both `logging` (contract)
   and `testing-unit` (guard).

The GRACE markup is already deployed in 91/91 production modules with the
`# region` / `# endregion` form. The rebalance moves shape content into that
markup, leaves specs as statements of **observable capability behavior**, and
fixes the stale items so the suite describes the system as built.

## What Changes

### Principle (established)

- **Specs** describe capability behavior at the system level: what the
  capability does, when, with what observable effect. Scenarios state
  behavior in GIVEN/WHEN/THEN (per project convention: WHEN/THEN).
- **GRACE contracts** in code describe shape: dataclass field inventories and
  defaults, function/method signatures, exception message formats, enum
  values, file inventories, format strings, configuration keys. The contract
  lives next to the code it describes and is bound to it by `# region` blocks.
- A requirement that merely enumerates a type's fields or a function's
  parameters is **not** a behavioral requirement. It is a shape statement and
  belongs in the corresponding `CLASS_*` / `FUNC_*` region's INVARIANTS or
  ENSURES.

### Stale-content fixes (correctness)

- `testing-unit` "Client queue-query unit verification": rewrite the
  `Status filter dispatches list_by_status`, `Jobs filter dispatches
  list_by_jobs`, `Both filters supplied raises ValueError`, `Neither filter
  returns empty list`, and `Returned dict shape and types are correct`
  scenarios to the current 6-key dict shape `{task_id, label, status,
  metadata, node}` with nested `node` object — no `ip` / `cloud` flat keys.
- `e2e-testing`: drop the `YaLogger.trace()` reference; the `log_records`
  fixture captures stdlib `LogRecord`s emitted via `logger.debug(msg,
  extra={...})`. Drop the `M-APPLICATION-ALLOCATE` propagation scenario; the
  equivalent `yascheduler.application.allocate_task` propagation scenario
  already exists and is the real naming convention.
- `test-db-integration`: replace `uow.nodes.add(Node(...))` →
  `uow.nodes.insert(NewNode(...))`; drop `get_by_ips`, `has_node`,
  `set_task_error` references; the typed `error` column is asserted via
  `task.fail()` / `task.reject()` and read back through `uow.tasks.get(id).error`.
- `package-facades` "Yascheduler facade public contract": fix the `node`
  object shape — `hostname` (not `ip`), `port`, `username`, `cloud` — sourced
  from the resolved `Node` aggregate. Update the `node object shape when
  allocated` scenario to use `Node(hostname=..., ...)`.

### Shape → GRACE moves (highest-impact)

- `domain-entities`: collapse the value-object shape requirements
  (`TaskId`, `NodeId`, `NewTask`, `Task`, `Node`, `NewNode`,
  `ConnectedMachine`, `Engine`, `ProcessResult`, `EngineRepository`,
  `MachineState`, `NodeStatus`, `materialize_task`) into short behavioral
  requirements ("the system SHALL provide a `Task` entity that owns its
  lifecycle transitions") with the field inventory + defaults + frozen
  invariant moved into `CLASS_*` INVARIANTS in code. The lifecycle-transition
  scenarios (run/reject/complete/fail/abandon) STAY in the spec — they are
  behavior, not shape.
- `domain-exceptions`: drop message-format-string literals from the spec.
  Keep "carries `<attr>`" statements (behaviorally observable). Move
  `f"machine ({node_id}) is busy"` and similar into `CLASS_*` INVARIANTS in
  the exception classes' GRACE regions.
- `config-value-objects`: drop the field-and-default enumerations from
  `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`, `Config`. Keep the
  capability statements, the importability scenarios, the validation
  behavior (`rejects invalid port`, `frozen`), and the
  "no `cloud_package_upgrade` field" backward-compat scenario. Defaults move
  into `CLASS_*` INVARIANTS.
- `package-facades` "Layers contract configuration": REMOVE the requirement
  entirely — it restates `pyproject.toml` keys. The contract is enforced by
  `import-linter` at lint time, not at runtime; the `layers` contract
  scenario under R3 is sufficient.

### Duplication consolidation

- `package-facades` R1 / R2 / R3: collapse each to one requirement with one
  or two representative scenarios. Remove the per-symbol scenarios
  ("Adapter imports Task via domain facade", "Application imports adapter
  symbols via infra layer facade", "Within-layer cross-subpackage imports
  also use the layer facade", etc.). The `import-linter` contract is the
  guard; per-symbol scenarios are documentation noise.
- `package-facades` "Layers contract configuration": REMOVE the requirement
  entirely — it restates `pyproject.toml` keys. The contract is enforced by
  `import-linter` at lint time; the `layers` contract scenario under R3 is
  sufficient.
- `package-facades` "Compat shim for yascheduler.client": REMOVE as a
  standalone requirement — the deep-import-path behavior is already covered
  by the modified `Public API stability` scenario "Deep import path resolves
  via compat shim". The shim module's contents (which symbols it re-exports,
  which it does NOT) live in the shim's `MODULE_CONTRACT` SCOPE.
- `package-facades` "Entrypoints layer facade": REMOVE as a standalone
  requirement — the eight-symbol enumeration is shape and lives in the
  entrypoints `MODULE_CONTRACT` SCOPE. The behavioral rule ("entrypoints
  facade is the layer facade for the entrypoints layer") is covered by the
  modified `Cross-package facade imports (R2)` requirement.
- `materialize_task` / `TaskCreated` emission: `domain-entities` keeps the
  authoritative scenario. `domain-events-and-dispatch` keeps the mapping
  table. `postgres-persistence` and `use-cases` reference the canonical
  site instead of restating the mechanism. (Mostly enacted in this change
  via the `domain-entities` MODIFIED requirement; full cross-capability
  consolidation deferred to follow-on change 9.2.)
- Jump-host stamping: `domain-entities` (Node field) remains authoritative.
  Other capabilities (`cli`, `cloud`, `ssh-infrastructure`, `orchestrator`)
  reduce their jump-host scenarios to one local-path scenario each plus a
  reference to `Node` as the source of truth. (Deferred to follow-on
  change 9.3.)
- Logging-discipline guard: `logging` keeps the contract.
  `testing-unit` keeps one reference scenario that names the two guards;
  the duplicated contract text is removed from `testing-unit`.

### Code-side GRACE markup additions (driven by the moves above)

For each shape relocation, the receiving `CLASS_*` / `FUNC_*` region is
extended with the moved content as INVARIANTS / ENSURES / SCOPE fields. New
markup is added only where a region currently lacks the field. No existing
region is split; every region continues to wrap its entire class/function.

## Capabilities

### New Capabilities
<!-- none — pure rebalance of existing specs -->

### Modified Capabilities
- `domain-entities`: value-object shape requirements collapsed to behavioral statements; field inventories, defaults, and frozen invariants relocated to GRACE `CLASS_*` INVARIANTS. Lifecycle-transition scenarios retained.
- `domain-exceptions`: message-format-string literals removed from spec; "carries `<attr>`" behavioral statements retained. Format strings relocated to exception classes' GRACE INVARIANTS.
- `config-value-objects`: field-and-default enumerations removed from spec; capability statements, validation behavior, and backward-compat scenarios retained. Defaults relocated to value-object GRACE INVARIANTS.
- `package-facades`: R1/R2/R3 collapsed to one requirement each with one or two representative scenarios; per-symbol scenarios removed; "Layers contract configuration", "Compat shim for yascheduler.client", and "Entrypoints layer facade" requirements removed (their content is shape and lives in the relevant `MODULE_CONTRACT` SCOPE; the behavioral coverage they provided is retained under the modified `R2`, `Public API stability`, and `Cross-package facade imports` requirements); `node.ip` → `node.hostname` fix in the facade public contract.
- `testing-unit`: stale 5-key dict scenarios rewritten to the 6-key `{..., node}` shape; logging-discipline duplicated text removed (reference to `logging` contract kept); legacy repository-method scenarios updated to current API.
- `e2e-testing`: `YaLogger.trace()` and `M-APPLICATION-ALLOCATE` references removed; `log_records` fixture described in terms of stdlib `LogRecord` capture via `logger.debug(msg, extra={...})`.
- `test-db-integration`: legacy API names (`add`, `get_by_ips`, `has_node`, `set_task_error`) replaced with the current repository API.
- `logging`: contract retained; duplicated guard-test detail trimmed (the authoritative guard spec lives in `testing-unit`).
- `postgres-persistence`: SQL-file inventory list removed from the "SQL file layout" requirement; the inventory lives in the persistence module's `MODULE_CONTRACT` SCOPE.

## Impact

- **Code (GRACE markup only, no behavior change)**: `CLASS_*` INVARIANTS
  extended on `TaskId`, `NodeId`, `NewTask`, `Task`, `Node`, `NewNode`,
  `ConnectedMachine`, `Engine`, `ProcessResult`, `EngineRepository`,
  `materialize_task`, `MachineState`, `NodeStatus`, `MachineBusyError`,
  `MachineConnectionError`, `LocalSettings`, `RemoteDefaults`,
  `PostgresDbConfig`, `Config`, the persistence module `MODULE_CONTRACT`
  (SQL-file inventory in SCOPE). Each region continues to wrap its full
  entity. No production logic changes; no public API surface changes.
- **Specs**: 9 capability spec files modified (delta specs in this change).
  Net spec line count is expected to drop materially (order of 30–40% on the
  affected capabilities) without losing any behavioral coverage.
- **Tests**: existing unit / integration / e2e tests unaffected. The
  `testing-unit` shape-contradiction fix changes the asserted dict shape in
  the affected tests to match production code (the tests were already broken
  vs. spec; this brings spec back in sync with code).
- **APIs**: none added, removed, or changed.
- **Dependencies**: none.
- **Config**: `pyproject.toml` `[tool.importlinter]` unchanged.
- **Active changes**: none in `openspec/changes/` outside `archive/` (the
  only other top-level entry, if present, would need a disjoint-line check
  at archive time).
- **Compatibility**: no behavior changes; the rebalance is documentation +
  GRACE markup. The stale-content fixes bring the spec back in sync with the
  shipped code.
