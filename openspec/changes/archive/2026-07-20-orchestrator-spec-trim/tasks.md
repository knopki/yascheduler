## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at a similar change was discarded specifically for violating
them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no `RAISES:`,
  no free-form labels. The spec's removed `SHALL NOT` sentences do NOT become
  a `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating
  the positive contract, or a `RATIONALE` Q/A if the rationale is the
  valuable part.
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text. One Q and one
  A per item, multi-item allowed when there are distinct reasons.
- **`PURPOSE` answers WHY, not WHAT.** "Manage the daemon's 4 producer-consumer
  loops" is WHAT and fails. "Keep the daemon running continuously by driving
  the four scheduling phases as resilient async loops that never block on a
  single failure" is WHY and passes. Existing `PURPOSE` fields in
  `orchestrator.py` already answer WHY — keep them, do not regress to WHAT.
- **Every `CLASS_*` / `METHOD_*` / `FUNC_*` region encloses the FULL entity.**
  For a class: the `class` line, the docstring, every field, every `__init__`
  line, every `self.<attr>` assignment, every nested `METHOD_*` / `BLOCK_*`
  region, through the trailing blank line before the next region marker. For
  a method: the decorator (if any), the `def`/`async def` line, the entire
  body, every nested `BLOCK_*` region, the trailing blank line. A region that
  closes before its entity ends (e.g. wrapping only the contract comment) is
  a defect. Nesting is allowed: `METHOD_*` and inner `BLOCK_*` regions live
  INSIDE the enclosing `CLASS_*` region; the `CLASS_*` `# endregion` comes
  after the last nested `# endregion`.
- **Comment-only diff.** No code logic, signature, decorator choice, docstring
  semantics, or import changes. Edits are `# region`/`# endregion` marker
  insertion and contract-field enrichment inside the marker block. The
  existing long internal `# region BLOCK_*` commentary inside
  `METHOD_connect_machine_consumer`, `METHOD_task_consumer_consumer`,
  `METHOD__select_and_insert_tmp`, `METHOD_print_stats`,
  `METHOD_create_producer_consumers`, `METHOD_stop`, etc. stays as-is (the
  narrative inside a region explains the non-obvious control flow and is
  non-region content).

## 1. Apply the orchestrator spec delta

- [x] 1.1 Apply the 11 MODIFIED requirements from `openspec/changes/orchestrator-spec-trim/specs/orchestrator/spec.md` to `openspec/specs/orchestrator/spec.md`, replacing each original requirement block in place. Preserve requirement header text exactly (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED operation. Headers to match (in spec order): `Orchestrator manages producer-consumer loops`, `Allocate loop`, `Consume loop`, `Deallocate loop`, `Connect machine loop`, `Stats logging`, `Orchestrator concurrency limits`, `Producer error resilience`, `Orchestrator.stop is idempotent and exception-safe`, `Free-machine selection gated on DB-enabled nodes`, `Free-machine loop isolates per-session failures`.
- [x] 1.2 Confirm the trimmed main spec lost exactly the 4 enumerated `SHALL NOT` instances in requirement bodies/scenario tails listed in `proposal.md` Why § 1: (a) "the orchestrator SHALL NOT read `clouds.configs` or hold `adapters`/`configs` dicts"; (b) "never touches `get_sftp`, `get_path`, or `get_quote` directly, never keys a session lookup by `ip`" (trailing clause of `Task deployment delegated to TaskDeployer...` THEN); (c) "no `log=` keyword argument is passed" (trailing clause of `Orchestrator constructed with unpacked settings...` THEN); (d) "The consumer SHALL NOT perform its own SSH teardown — teardown is owned by `deallocate_node`" (Deallocate loop body). Confirm the duplicated prose "All connection identity comes from the `Node` itself; `repository.connect` reads ... directly." (Connect machine loop body) and "The gate SHALL live in the use case, not in `MachineRepository`." (Free-machine selection gated on DB-enabled nodes body) are gone. Confirm every observable behavioral scenario (`#### Scenario:` count) is preserved: pre 34 → post 34. Confirm the 2 trimmed THEN clauses still carry their positive observable assertions.
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change validates AND the trimmed main spec validates AND no other spec regresses.

## 2. CLASS_Orchestrator — add INVARIANTS and RATIONALE absorbing the relocated constructor-shape rationale

The existing `CLASS_Orchestrator` region already wraps the full class (lines `class Orchestrator:` through the closing `# endregion CLASS_Orchestrator` after `METHOD_stop`); it already carries a WHY-shaped `PURPOSE`. Only the `INVARIANTS` and `RATIONALE` fields are added inside the existing contract block, between `PURPOSE` and the `class` line. No code change.

- [x] 2.1 Add an `INVARIANTS` field to the `CLASS_Orchestrator` region capturing the positive form of the relocated `SHALL NOT` content: orchestrator never accepts a `log=` parameter (enforced structurally by the static guard test `tests/unit/test_log_scope_discipline.py`; module-local logger via `logging.getLogger(__name__)`); orchestrator never accepts a `config: Config` aggregate — `LocalSettings` and `RemoteDefaults` are the application-layer projections (passed as separate keyword arguments); orchestrator never reads `clouds.configs` and never holds `adapters`/`configs` dicts — provider selection is delegated to `clouds.select_provider`; orchestrator dependencies are typed against domain Protocols (`MachineRepository`, `CloudProvisioner`) and concrete collaborators (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`).
- [x] 2.2 Add a `RATIONALE` Q/A field to the `CLASS_Orchestrator` region capturing the constructor-shape WHY: Q: why does the constructor take `local_settings=` and `remote_defaults=` as separate keyword arguments instead of a single `config: Config` aggregate? A: `Config` is a composition-root aggregate owned by `yascheduler.entrypoints`; `LocalSettings` and `RemoteDefaults` are the application-layer projections of the parts the orchestrator actually reads (sleep intervals, paths, keys dir). Passing the unpacked projections keeps `application → entrypoints` from importing `Config` at runtime or under `TYPE_CHECKING` (the layer direction is enforced by `lint-imports`).
- [x] 2.3 Verify `uv run ruff check yascheduler/application/orchestrator.py` and `uv run ruff format --check yascheduler/application/orchestrator.py` pass; `uv run pytest -m unit tests/unit/test_application_orchestrator.py tests/unit/test_log_scope_discipline.py tests/unit/test_application_no_adapter_imports.py tests/unit/test_di.py tests/unit/test_di_no_casts.py` is green.

## 3. METHOD_start_task_on_machine — add INVARIANTS absorbing the "never touches get_sftp/get_path/get_quote" negative space

The existing `METHOD_start_task_on_machine` region already wraps the full method (the `async def _start_task_on_machine(...)` line through the trailing `# endregion METHOD_start_task_on_machine`); it already carries a WHY-shaped `PURPOSE` and a nested `BLOCK_resolve_ncpus`. Only the `INVARIANTS` field is added inside the existing contract block, between `PURPOSE` and the `async def` line. No code change.

- [x] 3.1 Add an `INVARIANTS` field capturing the positive form of the relocated THEN-clause tail: method delegates the upload + spawn entirely to `self._task_deployer.start_task_on_machine(...)`; never touches `session.get_sftp()`, `session.get_path()`, or `session.get_quote()` directly; resolves the session by `task.allocated_node_id` (a `NodeId`), never by `ip`.
- [x] 3.2 Verify `uv run ruff check yascheduler/application/orchestrator.py` and `uv run ruff format --check yascheduler/application/orchestrator.py` pass; `uv run pytest -m unit tests/unit/test_orchestrator_start_task_on_machine.py tests/unit/test_application_orchestrator.py` is green.

## 4. METHOD_deallocator_consumer — add INVARIANTS absorbing the SSH-teardown-ownership negative space

The existing `METHOD_deallocator_consumer` region already wraps the full method (the `async def _deallocator_consumer(...)` line through the trailing `# endregion METHOD_deallocator_consumer`); it already carries a WHY-shaped `PURPOSE`. Only the `INVARIANTS` field is added inside the existing contract block, between `PURPOSE` and the `async def` line. No code change.

- [x] 4.1 Add an `INVARIANTS` field capturing the positive form of the relocated `SHALL NOT` content: consumer delegates SSH teardown to `deallocate_node(node, repository, clouds, uow_factory)`; consumer never calls `repository.contains(...)` or `repository.disconnect(...)` directly — teardown is owned by `deallocate_node`'s internal calls (cross-reference `FUNC_deallocate_node` REQUIRES in `deallocate_nodes.py`); consumer wraps the helper call in `try/except Exception` that logs `node_id`, `hostname`, and the error and continues to the next queued node without re-raising; consumer takes the `Node` straight from the queue message payload (no DB round-trip lookup).
- [x] 4.2 Verify `uv run ruff check yascheduler/application/orchestrator.py` and `uv run ruff format --check yascheduler/application/orchestrator.py` pass; `uv run pytest -m unit tests/unit/test_application_orchestrator.py tests/unit/test_abandon_node.py` is green.

## 5. METHOD__connect_grace_for — wrap the currently-unwrapped non-trivial private helper

`_connect_grace_for` is a non-trivial prefix → `connect_grace` lookup with a 120 s default; it lives inside the enclosing `CLASS_Orchestrator` region but currently has no entity-level contract region. Per the GRACE Python rule, wrap it. The new region opens one line above the `def` line and closes one line below the body, enclosing the FULL method per the Common rules. Only defined GRACE fields are used; `PURPOSE` answers WHY.

- [x] 5.1 Add `# region METHOD__connect_grace_for` ... `# endregion METHOD__connect_grace_for` enclosing the FULL method — the `def _connect_grace_for(self, cloud: str | None) -> int:` line, the body, the trailing blank line. The new region sits inside the enclosing `CLASS_Orchestrator` region, between the existing `METHOD_connect_machine_consumer` endregion and the existing `METHOD_allocator_consumer` region (or wherever the method physically lives in the file). `PURPOSE` (WHY: resolve the per-cloud `connect_grace` seconds for a node so the connect consumer can decide retry-vs-abandon without each call site re-deriving the prefix lookup and default). `INVARIANTS` (returns `120` when `cloud is None` OR when no `CloudConfig` in `self._config_clouds` matches `cfg.prefix == cloud` — the conservative fallback matches the slowest cloud default so the abandon path still fires for misconfigured or renamed cloud prefixes; the matching `CloudConfig.connect_grace` is returned on prefix match; sync, no I/O, no DB access).
- [x] 5.2 Verify `uv run ruff check yascheduler/application/orchestrator.py` and `uv run ruff format --check yascheduler/application/orchestrator.py` pass; `uv run pytest -m unit tests/unit/test_connect_grace.py tests/unit/test_connect_machine_consumer.py tests/unit/test_application_orchestrator.py` is green.

## 6. METHOD__allocator_producer — wrap the currently-unwrapped non-trivial private helper

`_allocator_producer` is a non-trivial producer that derives a dynamic TO_DO task limit from cloud capacity AND free-machine count, then queries TO_DO tasks up to that limit; it lives inside the enclosing `CLASS_Orchestrator` region but currently has no entity-level contract region. Per the GRACE Python rule, wrap it. The new region opens one line above the `async def` line and closes one line below the body, enclosing the FULL method per the Common rules. Only defined GRACE fields are used; `PURPOSE` answers WHY.

- [x] 6.1 Add `# region METHOD__allocator_producer` ... `# endregion METHOD__allocator_producer` enclosing the FULL method — the `async def _allocator_producer(self) -> AsyncGenerator[UMessage[TaskId, Task], None]:` line, the body (including the `ccap = await self._clouds_get_capacity()` call, the `tlim = max(...)` derivation, the `async with self._uow_factory() as uow:` block, the `logger.debug("ALLOCATOR_PRODUCER", ...)` trace, and the final `for task in tasks: yield ...` loop), the trailing blank line. The new region sits inside the enclosing `CLASS_Orchestrator` region, between the existing `METHOD_connect_machine_consumer` endregion (or `METHOD__connect_grace_for` endregion after task 5) and the existing `METHOD_allocator_consumer` region. `PURPOSE` (WHY: bound the next allocation wave to the larger of remaining cloud capacity or current free-machine count so the allocate queue never starves when capacity exists and never floods when it does not). `INVARIANTS` (the per-tick task limit is `max(cloud_capacity, len(repository.list_free(None)), 10)` — at least 10 to keep the queue warm on idle pools; TO_DO tasks are read once per tick via `uow.tasks.list_by_status({TaskStatus.TO_DO}, limit=tlim)`; emits an `ALLOCATOR_PRODUCER` trace DEBUG record with the task_ids when the batch is non-empty).
- [x] 6.2 Verify `uv run ruff check yascheduler/application/orchestrator.py` and `uv run ruff format --check yascheduler/application/orchestrator.py` pass; `uv run pytest -m unit tests/unit/test_application_orchestrator.py tests/unit/test_orchestrator_producer_resilience.py tests/unit/test_allocate_task_node_pairing.py` is green.

## 7. End-to-end verify

- [x] 7.1 Manual scan: every `# region CLASS_*`, `METHOD_*`, `BLOCK_*`, and `MODULE_CONTRACT` in `yascheduler/application/orchestrator.py` has a paired `# endregion` and wraps the entire entity (no orphaned trailing code outside the region; no region closes before its entity ends; nested `METHOD_*` / `BLOCK_*` regions live INSIDE their enclosing `CLASS_Orchestrator`; the `CLASS_Orchestrator` `# endregion` comes after the last nested `# endregion` — i.e. after `METHOD_stop`).
- [x] 7.2 Manual scan: no invented GRACE field names anywhere in the touched file — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` / `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`. Specifically, NO `SHALL NOT:` field anywhere in `orchestrator.py`.
- [x] 7.3 Manual scan: every `PURPOSE` field in `orchestrator.py` answers WHY, not WHAT. Spot-check the existing `MODULE_CONTRACT`, `CLASS_Orchestrator`, every `METHOD_*` (including the two new ones — `_connect_grace_for`, `_allocator_producer`), and confirm none regressed to a description.
- [x] 7.4 Manual scan: every `RATIONALE` field in `orchestrator.py` is in Q/A format ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that should be in `PURPOSE` / `INVARIANTS` / `SCOPE`.
- [x] 7.5 `openspec validate --all --json` passes (exit 0) after the spec delta is applied to `openspec/specs/orchestrator/spec.md` AND after the code-markup enrichment in tasks 2–6. The change directory `orchestrator-spec-trim` validates before archiving; the main `orchestrator` spec validates after the delta is applied.
- [x] 7.6 Full regression: `uv run pytest -m unit` is green; `uv run ruff check .` and `uv run ruff format --check .` are green on changed files; `uv run lint-imports` passes (the orchestrator module still respects the `layers` contract). The diff is `# region`/`# endregion` markup + comment-field enrichment + spec text trim only — no code logic, signature, decorator, docstring semantics, or import changes.
