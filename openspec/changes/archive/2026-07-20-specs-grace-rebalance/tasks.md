## 1. Stale-content spec fixes (correctness — no production change)

- [x] 1.1 In `openspec/specs/testing-unit/spec.md`, rewrite the "Client queue-query unit verification" scenarios to the 6-key dict shape `{task_id, label, status, metadata, node}`: drop the `ip` and `cloud` flat-key assertions; assert the nested `node` object instead. Match the delta in `specs-grace-rebalance/specs/testing-unit/spec.md`.
- [x] 1.2 In `openspec/specs/e2e-testing/spec.md`, rewrite the `log_records` fixture description: replace `YaLogger.trace()` with stdlib `logger.debug(msg, extra={...})` on a `logging.getLogger(__name__)` logger; replace the `M-APPLICATION-ALLOCATE` propagation scenario with the `yascheduler.application.allocate_task` propagation scenario. Match the delta.
- [x] 1.3 In `openspec/specs/test-db-integration/spec.md`, update the Node CRUD requirement to use the current API: `uow.nodes.insert(NewNode(...))` (not `add(Node(...))`); drop `get_by_ips`, `has_node`, `set_task_error` references; the typed `error` column is asserted via `task.fail()` / `task.reject()` and read back through `uow.tasks.get(id).error`. Match the delta.
- [x] 1.4 In `openspec/specs/package-facades/spec.md`, fix the `node` object shape in "Yascheduler facade public contract": `hostname` (not `ip`), `port`, `username`, `cloud`; update the `node object shape when allocated` scenario to construct `Node(node_id=NodeId(7), hostname=..., port=22, username="u", cloud="hetzner", ...)`. Match the delta.
- [x] 1.5 In `openspec/specs/e2e-testing/spec.md` and `openspec/specs/logging/spec.md`, verify the descendant-propagation scenarios agree on the logger namespace form: descendant `yascheduler.<dotted.module.path>` loggers (per `__name__`), no `M-*` namespace tokens.

## 2. Shape → GRACE moves: domain-entities

- [x] 2.1 In `openspec/specs/domain-entities/spec.md`, replace the value-object field-list requirements with the short behavioral statements from the delta (TaskId, NodeId, NewTask, Task, Node, NewNode, ConnectedMachine, Engine, ProcessResult, MachineState, NodeStatus, EngineRepository, materialize_task). Keep the lifecycle-transition scenarios for `Task`.
- [x] 2.2 In `yascheduler/domain/model.py` (and the per-symbol modules where each class lives), extend each `CLASS_*` GRACE region with INVARIANTS capturing the field inventory, defaults, and `frozen=True` declaration for: `TaskId`, `NodeId`, `NewTask`, `Task`, `Node`, `NewNode`, `ConnectedMachine`, `Engine`, `ProcessResult`, `MachineState`, `NodeStatus`, `EngineRepository`. Each region SHALL continue to wrap the entire class (open `# region CLASS_X` before `class X:` / `@dataclass`, close `# endregion CLASS_X` after the last method).
- [x] 2.3 In `yascheduler/domain/model.py`, extend the `FUNC_materialize_task` region with ENSURES capturing the `TaskCreated` constructor argument shape (`task_id`, `webhook_url`, `webhook_custom_params`, `engine_name`) and the `replace(task, events=(event,))` postcondition.
- [x] 2.4 Run `uv run pytest -m unit` — domain-entity unit tests MUST stay green (no behavior change).

## 3. Shape → GRACE moves: domain-exceptions

- [x] 3.1 In `openspec/specs/domain-exceptions/spec.md`, drop the message-format-string literals from `MachineBusyError`, `MachineConnectionError`, `TaskError hierarchy`, `SchedulingError hierarchy` requirements. Keep "carries `<attr>`" statements. Match the delta.
- [x] 3.2 In `yascheduler/domain/exceptions.py`, extend each `CLASS_*` GRACE region with INVARIANTS capturing the message format string for: `MachineBusyError` (`f"machine ({node_id}) is busy"`), `MachineConnectionError` (`f"cannot connect to machine ({node_id}) at {hostname}: {reason}"`), `TaskNotTodoError`, `TaskNotRunningError`, `NoCompatibleNodeError`, `CloudCapacityExhaustedError`. Each region SHALL continue to wrap the entire class.
- [x] 3.3 Run `uv run pytest -m unit` — domain-exception unit tests MUST stay green.

## 4. Shape → GRACE moves: config-value-objects

- [x] 4.1 In `openspec/specs/config-value-objects/spec.md`, drop the field-and-default enumerations from `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`, `Config` requirements. Keep capability statements, validation behavior, and backward-compat scenarios. Match the delta.
- [x] 4.2 In the value-object modules (`yascheduler/domain/settings.py` for `LocalSettings`/`RemoteDefaults`, `yascheduler/infra/persistence/...` for `PostgresDbConfig`, `yascheduler/entrypoints/config.py` for `Config`), extend each `CLASS_*` GRACE region with INVARIANTS capturing the field inventory and per-field defaults. Each region SHALL continue to wrap the entire class.
- [x] 4.3 Run `uv run pytest -m unit` — config value-object unit tests MUST stay green.

## 5. Shape → GRACE moves: postgres-persistence

- [x] 5.1 In `openspec/specs/postgres-persistence/spec.md`, remove the exhaustive SQL-file-name list from the "SQL file layout" requirement; keep the loading-cache rule and the schema-vs-migration ownership split. Match the delta.
- [x] 5.2 In the persistence package's `MODULE_CONTRACT` (top of `yascheduler/infra/persistence/__init__.py` or the relevant loader module), extend SCOPE with the exhaustive `task/*.sql` and `node/*.sql` file inventory.
- [x] 5.3 Run `uv run pytest -m unit` and `uv run pytest -m integration` — persistence tests MUST stay green.

## 6. package-facades collapse

- [x] 6.1 In `openspec/specs/package-facades/spec.md`, collapse R1, R2, R3 each to one requirement with one or two representative scenarios per the delta. Remove the per-symbol scenarios listed in the delta's "Per-symbol R1/R2/R3 scenarios" REMOVED entry.
- [x] 6.2 Remove the "Layers contract configuration" requirement (it restated `pyproject.toml` keys).
- [x] 6.3 Remove the "Compat shim for yascheduler.client" standalone requirement (covered by the stability scenario; shim contents live in shim's `MODULE_CONTRACT`).
- [x] 6.4 Remove the "Entrypoints layer facade" standalone requirement (eight-symbol enumeration is shape; covered by R2 + the facade module's `MODULE_CONTRACT` SCOPE).
- [x] 6.5 In `yascheduler/client.py` (the compat shim), extend the `MODULE_CONTRACT` SCOPE to declare: re-exports `Yascheduler`; does NOT re-export `Config` (asserted by the dropped "Shim does not re-export Config" scenario).
- [x] 6.6 In `yascheduler/entrypoints/__init__.py`, extend the `MODULE_CONTRACT` SCOPE to enumerate the eight re-exported wiring symbols (`Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`, `Config`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`).
- [x] 6.7 In `yascheduler/__init__.py`, extend the `MODULE_CONTRACT` SCOPE to enumerate the package-facade exports (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `__version__`).
- [x] 6.8 Run `uv run lint-imports` and `uv run pytest -m unit` — `import-linter` contract MUST still pass; facade tests MUST stay green.

## 7. logging / testing-unit de-duplication

- [x] 7.1 In `openspec/specs/testing-unit/spec.md`, remove the duplicated "Logging discipline guard tests" contract text and the per-collaborator enumeration; keep the new "Logging discipline guard tests (reference)" requirement (one behavioral rule + the two scenarios from the delta).
- [x] 7.2 Confirm the `logging` capability remains the authoritative owner of the contract text ("Module-local stdlib logger binding" requirement and its scenarios).
- [x] 7.3 Run `uv run pytest -m unit` — the two logging-discipline guard tests MUST stay green; no other unit test should be affected.

## 8. Validation

- [x] 8.1 Run `openspec validate --all --json` — MUST pass with zero issues after applying deltas 1–7 to the main specs.
- [x] 8.2 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — MUST all pass.
- [x] 8.3 Run `uv run pytest -m unit` — MUST stay green.
- [ ] 8.4 (If integration tests are run) `uv run pytest -m integration` — MUST stay green. No DB/SSH behavior changes; assume Docker available.

## 9. Follow-on changes (out of scope for THIS change — list only)

- [ ] 9.1 Slim CLI verbatim-message tables: move the 6-row "yasetnode output channels and verbatim success messages" table from `cli` spec to the yasetnode module's `MODULE_CONTRACT` SCOPE; keep one behavioral "verbatim messages emitted after commit" scenario in the spec. (Separate proposal.)
- [ ] 9.2 Consolidate `materialize_task` / `TaskCreated` references in `postgres-persistence` and `use-cases` to point at the `domain-entities` canonical site. (Separate proposal.)
- [ ] 9.3 Collapse the jump-host-stamping scenarios in `cli`, `cloud`, `ssh-infrastructure`, `orchestrator` to one local-path scenario each + a reference to `Node` as the source of truth. (Separate proposal.)
- [ ] 9.4 Consider merging `engine-config-parsing` into `config-value-objects`. (Separate proposal — borderline.)
- [ ] 9.5 Consider merging `postgres-schema-apply` and `db-migrations` into one "Database schema lifecycle" capability. (Separate proposal — borderline.)
- [ ] 9.6 Slim the orchestrator spec's constructor-shape scenario ("Orchestrator constructed with unpacked settings and three collaborators") — move the constructor signature to `CLASS_Orchestrator` INVARIANTS. (Separate proposal.)
