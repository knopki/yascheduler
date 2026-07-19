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
- **`PURPOSE` answers WHY, not WHAT.** "Validate engine and input files,
  construct a NewTask, persist via UoW, and return the generated TaskId" is
  WHAT and fails. "Accept validated task requests from clients and persist
  them so the daemon's allocator can pick them up for scheduling" is WHY and
  passes. Existing `PURPOSE` fields in the touched files already answer WHY —
  keep them, do not regress to WHAT.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region continues to enclose the
  FULL entity.** This is already the case in every touched file — every
  public function and the `AllocationTracker` class already carry a wrapping
  region that encloses the full entity (decorator, `def`/`class` line,
  docstring, body, every nested `BLOCK_*`, trailing blank line). The change
  makes no structural region changes; only contract fields inside those
  existing regions are enriched, between `PURPOSE` and the `def`/`class` line.
  A region that closes before its entity ends (e.g. wrapping only the
  contract comment) is a defect; verify none exists after the change.
  Nesting is allowed: `METHOD_*` and inner `BLOCK_*` regions live INSIDE the
  enclosing `CLASS_AllocationTracker` region; the `CLASS_AllocationTracker`
  `# endregion` comes after the last nested `# endregion`.
- **Comment-only diff.** No code logic, signature, decorator choice,
  docstring semantics, or import changes. Edits are contract-field enrichment
  inside existing `# region` blocks. The existing long internal `# region
  BLOCK_*` commentary inside `FUNC__select_and_insert_tmp`,
  `FUNC__persist_node_with_cleanup`, `FUNC_allocate_task`,
  `FUNC__find_free_machines`, `FUNC_deallocate_node`, `FUNC__decide_-
  finalisation`, `FUNC_abandon_node` stays as-is (the narrative inside a
  region explains the non-obvious control flow and is non-region content).

## 1. Apply the use-cases spec delta

- [x] 1.1 Apply the 7 MODIFIED requirements from `openspec/changes/use-cases-spec-trim/specs/use-cases/spec.md` to `openspec/specs/use-cases/spec.md`, replacing each original requirement block in place. Preserve requirement header text exactly (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED operation. Headers to match (in spec order): `SubmitTask use case`, `AllocateTask use case`, `DeallocateIdleNodes use case`, `AbandonNode use case`, `ConsumeTask use case`, `QueryTasks use case`, `AllocationTracker tracks in-flight cloud allocations`.
- [x] 1.2 Confirm the trimmed main spec contains zero `SHALL NOT` / `shall not` instances in requirement bodies (all 9 enumerated in `proposal.md` Why § 1 are gone; the one `SHALL NOT` surviving in the `AbandonNode` body — "SHALL NOT suppress the subsequent DB-row removal" — is a positive observable postcondition phrased as a negative, leave it). Confirm the implementation-narrative paragraphs enumerated in `proposal.md` Why § 2 are gone (typed-field routing, cloud-fallback sequencing, disable-before-delete ordering, abandon 4-step flow, transient-vs-permanent priority rule, facade-boundary int/TaskId prose, internal-to-orchestrator aside). Confirm the stale `AbandonNode` 4-step flow body and the stale scenario "No matching TO_DO task skips tracker discard" are gone. Confirm every observable behavioral scenario (`#### Scenario:` count) is preserved: pre 31 → post 34 (drop 1 stale, add 1 missing AllocateTask empty-platforms short-circuit, add 3 accurate AbandonNode scenarios).
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change validates AND the trimmed main spec validates AND no other spec regresses.

## 2. submit_task.py — enrich FUNC_submit_task

The existing `FUNC_submit_task` region already wraps the full function (the `async def submit_task(...)` line through the trailing `# endregion FUNC_submit_task`); it already carries a WHY-shaped `PURPOSE` and the nested `BLOCK_validate`, `BLOCK_create_task`, `BLOCK_persist`. Only `INVARIANTS` and `RATIONALE` fields are added inside the existing contract block, between `PURPOSE` and `REQUIRES` (or between `PURPOSE` and the `async def` line if no `REQUIRES`). No code change.

- [x] 2.1 Add an `INVARIANTS` field capturing the relocated typed-field routing invariants: `NewTask` is constructed without `task_id` (the DB-generated `TaskId` is assigned inside `uow.tasks.insert`); `remote_folder` and `error` are never set on `NewTask` (`remote_folder` is assigned at `run` time; `error` only by `reject`/`fail`/`abandon` on a post-persistence `Task`); `TaskCreated` is attached inside `uow.tasks.insert`, not by this use case; `status` defaults to `TaskStatus.TO_DO` and `allocated_node_id` to `None` via `NewTask` field defaults.
- [x] 2.2 Add a `RATIONALE` Q/A field capturing the WHY of the `extra` dict routing: Q: why is every non-typed key in the caller `metadata` routed to `extra` instead of being rejected or silently dropped? A: a flat `metadata` dict keeps the call surface stable (clients pass one dict, not a growing typed-arg list); the six known typed fields (`engine`, `remote_folder`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`) are projected onto `NewTask` fields, and everything else (the input-file payloads — file contents as values, file names as keys) is preserved verbatim in `extra` for the spawn step to write to the remote machine.
- [x] 2.3 Verify `uv run ruff check yascheduler/application/submit_task.py` and `uv run ruff format --check yascheduler/application/submit_task.py` pass; `uv run pytest -m unit tests/unit/test_cli_submit.py` is green.

## 3. allocate_task.py — enrich FUNC_allocate_task and FUNC__select_and_insert_tmp

The existing `FUNC_allocate_task` and `FUNC__select_and_insert_tmp` regions already wrap their full functions; both already carry WHY-shaped `PURPOSE`. `FUNC_allocate_task` already has `REQUIRES` / `ENSURES` / `RATIONALE` (the enabled-gate rationale); `FUNC__select_and_insert_tmp` already has `PURPOSE` / `ENSURES`. Only `INVARIANTS` fields are added (and one new `RATIONALE` Q/A on `FUNC_allocate_task` for the critical-section ownership). No code change.

- [x] 3.1 Add an `INVARIANTS` field to `FUNC_allocate_task` capturing the positive form of the relocated `SHALL NOT` content: imports `yascheduler.infra` only under `TYPE_CHECKING` (enforced structurally by `tests/unit/test_application_no_adapter_imports.py`); accepts no `adapters` / `configs` parameters — provider selection is delegated to `clouds.select_provider`; the cloud-fallback critical section (tracker dedup → capacity check → provider selection → tmp-node insert → cloud allocation → final node persistence) is owned by this use case, not the orchestrator.
- [x] 3.2 Add a `RATIONALE` Q/A to `FUNC_allocate_task` capturing the WHY of critical-section ownership: Q: why does the use case own the cloud-fallback critical section (tracker dedup, capacity check, tmp-node insert, cloud allocation, final persist) rather than the orchestrator? A: the `allocation_lock` must serialize the capacity-read → tmp-insert → cloud-allocate sequence so concurrent `allocate_task` calls do not over-provision; collocating the critical section with the dedup gate makes the atomicity boundary explicit and keeps the orchestrator free of capacity-counting concerns.
- [x] 3.3 Add an `INVARIANTS` field to `FUNC__select_and_insert_tmp` capturing the relocated concurrency contract: the `allocation_lock` serializes the capacity-read through tmp-insert sequence so concurrent allocators see the committed tmp-node and do not overshoot `max_nodes`; the tmp-node is committed before the lock is released; the function returns `None` when `clouds.select_provider` returns `None` (no capacity or op semaphore locked).
- [x] 3.4 Verify `uv run ruff check yascheduler/application/allocate_task.py` and `uv run ruff format --check yascheduler/application/allocate_task.py` pass; `uv run pytest -m unit tests/unit/test_allocate_task_node_pairing.py tests/unit/test_allocate_task_failure_modes.py tests/unit/test_application_no_adapter_imports.py` is green.

## 4. consume_task.py — enrich FUNC_consume_task, FUNC__decide_finalisation, FUNC__format_download_error

The existing `FUNC_consume_task`, `FUNC__decide_finalisation`, and `FUNC__format_download_error` regions already wrap their full functions; all carry WHY-shaped `PURPOSE`. `FUNC__decide_finalisation` already has `ENSURES`; `FUNC__format_download_error` has `PURPOSE` only. Add `INVARIANTS` / `RATIONALE` / `ENSURES` fields inside the existing contract blocks. No code change.

- [x] 4.1 Add an `INVARIANTS` field to `FUNC_consume_task` capturing the positive form of the relocated `SHALL NOT` content: imports SFTP retry / backoff infrastructure from `yascheduler.infra` only under `TYPE_CHECKING` (enforced structurally by `tests/unit/test_application_no_adapter_imports.py`); SFTP download with retry and error classification is delegated to `output_downloader.download_outputs(session, ...)` — no direct SFTP / backoff calls in this module.
- [x] 4.2 Add a `RATIONALE` Q/A to `FUNC__decide_finalisation` capturing the WHY of the permanent-takes-priority rule: Q: when both `permanent_errors` and `transient_errors` are non-empty, why does permanent take priority and the task fail? A: a permanent error means at least one output file is unrecoverable, so the task cannot succeed on retry; failing fast avoids burning retry budget on a doomed task and surfaces the unrecoverable file to the operator.
- [x] 4.3 Add an `ENSURES` field to `FUNC__format_download_error` capturing the relocated format contract: the returned string is `"Download error: <path>: <msg>, <path>: <msg>"` (entries joined by `", "`); entries with `path=None` render as the bare `"<msg>"` (no leading `<path>: `); an empty input list returns the bare prefix `"Download error: "` (defensive; the caller never invokes the function with an empty list because the finalise path only constructs the message when `combined_errors` is non-empty).
- [x] 4.4 Verify `uv run ruff check yascheduler/application/consume_task.py` and `uv run ruff format --check yascheduler/application/consume_task.py` pass; `uv run pytest -m unit tests/unit/test_consume_task.py tests/unit/test_application_no_adapter_imports.py` is green.

## 5. deallocate_nodes.py — enrich FUNC_deallocate_node and FUNC_deallocate_nodes

The existing `FUNC_deallocate_node` and `FUNC_deallocate_nodes` regions already wrap their full functions; both carry WHY-shaped `PURPOSE`. `FUNC_deallocate_node` already has `REQUIRES` / `ENSURES` / `RATIONALE` (the disable-before-delete ordering rationale); `FUNC_deallocate_nodes` has `PURPOSE` / `ENSURES`. Only `INVARIANTS` fields are added. No code change.

- [x] 5.1 Add an `INVARIANTS` field to `FUNC_deallocate_node` capturing the relocated ordering invariants: SSH disconnect runs before the `if node.cloud:` guard so it executes unconditionally for both cloud and static nodes (a transient SSH failure does not skip teardown); the disable+remove bracket (DB disable before cloud VM delete, DB remove after cloud VM delete) protects against allocator re-selection on cloud-deletion failure (a disabled node is invisible to the free-machine selection); cloud VM deletion is conditional on `node.cloud` because static nodes have no cloud VM to delete; per-node teardown is owned by this helper, not by the caller — the caller wraps the call in `try/except Exception` and does not call `repository.contains` / `repository.disconnect` directly.
- [x] 5.2 Add an `INVARIANTS` field to `FUNC_deallocate_nodes` capturing the relocated correlation contract: internal log lines in both `deallocate_nodes` and the per-node helper include both `node_id` and `hostname` for cross-cutting correlation; phase-2 (collect free disabled cloud nodes) returns `Node` objects read from `uow.nodes.list_disabled()`, each carrying `node_id`, so the orchestrator can call `deallocate_node(node, ...)` directly without a DB round-trip.
- [x] 5.3 Verify `uv run ruff check yascheduler/application/deallocate_nodes.py` and `uv run ruff format --check yascheduler/application/deallocate_nodes.py` pass; `uv run pytest -m unit` for any test importing `yascheduler.application.deallocate_nodes` is green.

## 6. abandon_node.py — enrich FUNC_abandon_node

The existing `FUNC_abandon_node` region already wraps the full function (the `async def abandon_node(...)` line through the trailing `# endregion FUNC_abandon_node`); it already carries a WHY-shaped `PURPOSE` / `REQUIRES` / `ENSURES` and the nested `BLOCK_cloud_delete`, `BLOCK_remove_row`, `BLOCK_discard_by_node`. Add `INVARIANTS` and `RATIONALE` fields inside the existing contract block. No code change.

- [x] 6.1 Add an `INVARIANTS` field capturing the positive form of the relocated `SHALL NOT` content: never calls `repository.disconnect` — the node was never registered in the repository (that is why it is being abandoned); never modifies `node.enabled` or calls `uow.nodes.disable` — the row is removed directly; never marks the task `FAILED` or emits a domain event — the task re-enters `allocate_task` on the next cycle because the `allocated_node_id` FK is `ON DELETE SET NULL` (removing the node row nulls the task's `allocated_node_id`, freeing it for re-allocation); imports `yascheduler.infra` only under `TYPE_CHECKING` (enforced by `tests/unit/test_application_no_adapter_imports.py`); the cloud VM deletion is best-effort (logged at error on failure, never raised); the DB row removal failure is re-raised (caller keeps the worker alive); the tracker discard runs via `tracker.discard_by_node(node.node_id)` AFTER successful DB-row removal (a remove failure skips the discard — the entry stays until the next abandon attempt).
- [x] 6.2 Add a `RATIONALE` Q/A field capturing the WHY of `discard_by_node` instead of a task lookup: Q: why does `abandon_node` call `tracker.discard_by_node(node.node_id)` unconditionally rather than looking up the TO_DO task whose `allocated_node_id == node.node_id` and discarding by `task_id`? A: `discard_by_node` is simpler (no `uow.tasks` read), defensive (catches multi-entry corruption and returns the count for an ambiguous-tracker warning), and correct (the task naturally re-allocates on the next cycle because the FK is `ON DELETE SET NULL`); a per-task lookup would add a DB round-trip and a conditional discard branch for no behavioral benefit. This also fixes the spec-vs-code drift: the prior spec described a 4-step flow with a task lookup + conditional `tracker.discard(task_id)`, which the `2026-07-10-fix-tracker-node-link-leak` refactor replaced.
- [x] 6.3 Verify `uv run ruff check yascheduler/application/abandon_node.py` and `uv run ruff format --check yascheduler/application/abandon_node.py` pass; `uv run pytest -m unit tests/unit/test_abandon_node.py tests/unit/test_allocation_tracker.py tests/unit/test_application_no_adapter_imports.py` is green.

## 7. query_tasks.py — enrich FUNC_query_tasks

The existing `FUNC_query_tasks` region already wraps the full function; it carries WHY-shaped `PURPOSE` / `REQUIRES` / `ENSURES` and the nested `BLOCK_validate_input`, `BLOCK_empty_dispatch`, `BLOCK_query` (with inner `BLOCK_batch_load_nodes`). Add `INVARIANTS` and `SCOPE` fields inside the existing contract block. No code change.

- [x] 7.1 Add an `INVARIANTS` field capturing the positive form of the relocated `SHALL NOT` content: read-only — never calls `uow.commit` on the opened UoW; imports `yascheduler.infra` only under `TYPE_CHECKING` (enforced by `tests/unit/test_application_no_adapter_imports.py`); a single UoW is opened for both the task read and the batched node read so the snapshot is consistent; node IDs are deduplicated while preserving a stable order for deterministic tests.
- [x] 7.2 Add a `SCOPE` field capturing the relocated facade-boundary exclusion: returns raw domain `Task` aggregates and a `dict[NodeId, Node]` of allocated nodes; `NOT:` projection of a nested `node` field into task dicts — that is the `Yascheduler.queue_get_tasks_async` facade's responsibility (the facade is the sole `int` / `TaskId` boundary on this path, wrapping `[TaskId(i) for i in jobs]` before calling `query_tasks(jobs=[TaskId(...)], ...)`).
- [x] 7.3 Verify `uv run ruff check yascheduler/application/query_tasks.py` and `uv run ruff format --check yascheduler/application/query_tasks.py` pass; `uv run pytest -m unit tests/unit/test_query_tasks.py tests/unit/test_client_query.py tests/unit/test_application_no_adapter_imports.py` is green.

## 8. allocation_tracker.py — enrich CLASS_AllocationTracker

The existing `CLASS_AllocationTracker` region already wraps the full class (the `class AllocationTracker:` line through the trailing `# endregion CLASS_AllocationTracker`); it carries WHY-shaped `PURPOSE` and `INVARIANTS` (the existing `INVARIANTS` says "In-memory only — daemon restart resets state; entries dict is the sole source of truth"). The two `METHOD_*` regions (`METHOD_set_node`, `METHOD_discard_by_node`) already wrap their full methods. Add a `RATIONALE` Q/A and extend `INVARIANTS` on the class; no `METHOD_*` enrichment is required (the methods are simple enough that their docstrings already state the contract). No code change.

- [x] 8.1 Extend the `CLASS_AllocationTracker` `INVARIANTS` field with the relocated "internal to orchestrator" invariant: constructed once by the orchestrator and injected into `allocate_task`, `consume_task`, and `abandon_node`; never crosses the public `Yascheduler` facade boundary; the `add` / `set_node` / `discard` / `discard_by_node` / `__contains__` surface is the full public API of the class — no other methods are exposed.
- [x] 8.2 Add a `RATIONALE` Q/A field to `CLASS_AllocationTracker` capturing the WHY of the dual-key discard surface: Q: why does the tracker expose both `discard(task_id)` and `discard_by_node(node_id)`? A: `discard(task_id)` is the happy-path release (the consume use case knows the `task_id` it just finalised); `discard_by_node(node_id)` is the abandon-path release (the abandon use case knows only the `node_id` whose VM was deleted, not the `task_id` that was tracked against it — the in-memory `_entries` dict is keyed by `task_id` but links a `node_id` value for exactly this discard-by-node path).
- [x] 8.3 Verify `uv run ruff check yascheduler/application/allocation_tracker.py` and `uv run ruff format --check yascheduler/application/allocation_tracker.py` pass; `uv run pytest -m unit tests/unit/test_allocation_tracker.py` is green.

## 9. End-to-end verify

- [x] 9.1 Manual scan: every `# region CLASS_*`, `FUNC_*`, `METHOD_*`, `BLOCK_*`, and `MODULE_CONTRACT` in the touched files (`submit_task.py`, `allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`, `abandon_node.py`, `query_tasks.py`, `allocation_tracker.py`) has a paired `# endregion` and wraps the entire entity (no orphaned trailing code outside the region; no region closes before its entity ends; nested `METHOD_*` / `BLOCK_*` regions live INSIDE their enclosing `CLASS_*` / `FUNC_*`; the `CLASS_AllocationTracker` `# endregion` comes after the last nested `# endif`).
- [x] 9.2 Manual scan: no invented GRACE field names anywhere in the touched files — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` / `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`. Specifically, NO `SHALL NOT:` field anywhere in `yascheduler/application/*.py`.
- [x] 9.3 Manual scan: every `PURPOSE` field in the touched files answers WHY, not WHAT. Spot-check the existing `MODULE_CONTRACT` and `FUNC_*` / `CLASS_*` / `METHOD_*` regions, and confirm none regressed to a description (e.g. "Validate engine and input files, construct a NewTask, persist via UoW, and return the generated TaskId" is WHAT — fail; "Accept validated task requests from clients and persist them so the daemon's allocator can pick them up for scheduling" is WHY — pass).
- [x] 9.4 Manual scan: every `RATIONALE` field in the touched files is in Q/A format ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that should be in `PURPOSE` / `INVARIANTS` / `SCOPE`.
- [x] 9.5 `openspec validate --all --json` passes (exit 0) after the spec delta is applied to `openspec/specs/use-cases/spec.md` AND after the code-markup enrichment in tasks 2–8. The change directory `use-cases-spec-trim` validates before archiving; the main `use-cases` spec validates after the delta is applied.
- [x] 9.6 Full regression: `uv run pytest -m unit` is green; `uv run ruff check .` and `uv run ruff format --check .` are green on changed files; `uv run lint-imports` passes (the application modules still respect the `layers` contract). The diff is `# region`/`# endregion` contract-field enrichment + spec text trim only — no code logic, signature, decorator, docstring semantics, or import changes.
