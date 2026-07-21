## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at a similar change was discarded specifically for violating
them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no `RAISES:`,
  no free-form labels. The spec's removed `SHALL NOT` sentences do NOT
  become a `SHALL NOT:` contract field — they become an `INVARIANTS` entry
  stating the positive contract, or are dropped when the behavior is
  already asserted by a positive Gherkin scenario.
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text. One Q and
  one A per item, multi-item allowed when there are distinct reasons. If
  the relocated content answers "what always holds?" it goes in
  `INVARIANTS`, not `RATIONALE`. The `queue.py` enrichment in this change
  adds zero `RATIONALE` lines — the relocated dedup content is
  invariant-shaped, not rationale-shaped.
- **`PURPOSE` answers WHY, not WHAT.** "Async queue with deduplication"
  is WHAT and fails. "Prevent the daemon from processing the same task
  event twice across overlapping producer-consumer cycles" is WHY and
  passes. The existing `PURPOSE` lines on `CLASS_UMessage`,
  `CLASS_UniqueQueue`, and `METHOD_put` in `queue.py` are already
  WHY-shaped — leave them as-is.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.**
  For a class: the `@dataclass(...)` / other decorator (if any), the
  `class` line, the docstring, every field, every `__init__` line, every
  `self.<attr>` assignment, every nested `METHOD_*` / `BLOCK_*` region,
  through the trailing blank line before the next region marker. For a
  function: the decorator (if any), the `def` / `async def` line, the
  entire body, every nested `BLOCK_*` region, the trailing blank line.
  A region that closes before its entity ends (e.g. wrapping only the
  contract comment) is a defect. Nesting is allowed: `METHOD_*` and inner
  `BLOCK_*` regions live INSIDE the enclosing `CLASS_*` region; the
  `CLASS_*` `# endregion` comes after the last nested `# endregion`. The
  existing regions in `queue.py` are already correctly wrapped — verify
  before enrichment, do not re-wrap.
- **Comment-only diff.** No code logic, signature, decorator choice,
  docstring semantics, or import changes. Edits are `# region` / `# endregion`
  marker insertion and contract-field enrichment inside the marker block.
  The single production-code touch in this change is three `INVARIANTS`
  lines inside existing `CLASS_*` / `METHOD_*` regions on
  `yascheduler/application/queue.py`. No new regions are added; the
  trivial methods (`_get`, `get`, `task_done`, `item_done`, `psize`,
  `__init__`) are left unmarked per the GRACE proportional rule.

## 1. Apply the testing-unit spec delta

- [x] 1.1 Apply the 18 MODIFIED requirements from `openspec/changes/testing-unit-spec-trim/specs/testing-unit/spec.md` to `openspec/specs/testing-unit/spec.md`, replacing each original requirement block in place. Preserve requirement header text exactly (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED operation. Headers to match (in spec order): `Domain entities lifecycle`, `Domain exception hierarchy`, `Domain port Protocol conformance`, `Domain services`, `Config parsing and validation`, `Persistence adapter with mocked pg8000`, `Application use cases`, `Orchestrator lifecycle`, `Dependency injection factories`, `CLI behavioral tests`, `Client queue-submit characterization`, `UniqueQueue`, `Remote machine management`, `OS check functions`, `RemoteMachineAdapter structure`, `WebhookPayload`, `Client queue-query unit verification`, `Logging discipline guard tests`.
- [x] 1.2 Apply the 1 REMOVED requirement: delete the entire `### Requirement: Shared test fixtures` block from `openspec/specs/testing-unit/spec.md` (requirement header, body, and the single `#### Scenario: Mock factories provided for remote machine and clouds` block). The target files `tests/fixtures/mock_remote_machine.py` and `tests/fixtures/mock_clouds.py` were deleted in `3fba272` / `9d1350c`; the scenario cannot pass; the requirement is a phantom.
- [x] 1.3 Confirm the trimmed main spec contains zero `SHALL NOT` / `shall not` instances in requirement bodies (all 6 enumerated in `proposal.md` Why § 1 are gone; the only remaining `NOT` language lives inside Gherkin scenario bodies where it expresses observable behavior — e.g. `MachineBusyError` "no `hostname` attribute", "no `from_config_parser_section` or `get_valid_config_parser_fields` classmethods", `make_cli_deps` "not the daemon graph"). Confirm every observable behavioral scenario (`#### Scenario:` count) is preserved: pre 44 → post 43 (the one `Mock factories provided` scenario goes away with its removed requirement).
- [x] 1.4 `openspec validate --all --json` passes (exit 0). The change validates AND the trimmed main spec validates AND no other spec regresses (currently 20 specs + 7 in-flight `*-spec-trim` changes, minus the two invalid stubs `engine-config-parsing-spec-trim` and `postgres-schema-apply-spec-trim` which are out of scope here).

## 2. queue.py — enrich existing CLASS_UMessage, CLASS_UniqueQueue, METHOD_put with INVARIANTS

The existing regions in `yascheduler/application/queue.py` are already correctly wrapped (verified before enrichment: `MODULE_CONTRACT` lines 2-7, `CLASS_UMessage` lines 24-48 enclosing `@dataclass`, `class` line, `__slots__`, both fields, and the nested `BLOCK_define_id_only_equality` containing `__eq__` + `__hash__`; `CLASS_UniqueQueue` lines 51-110 enclosing `class` line, class attrs, `__init__`, `_get`, `get`, `METHOD_put` (lines 83-93), `task_done`, `item_done`, `psize`; `METHOD_put` lines 83-93 enclosing the `async def put` line, docstring, body, trailing blank). No re-wrapping required. Only defined GRACE fields are used; the existing `PURPOSE` lines are already WHY-shaped and stay unchanged; zero `RATIONALE` additions.

- [x] 2.1 Add a single `# INVARIANTS: ...` line inside the `CLASS_UMessage` region, between the existing `# PURPOSE: ...` line and the `@dataclass(frozen=True, eq=False)` line. Text: "`__eq__` and `__hash__` consult `id` only; `payload` is excluded from both — an unhashable `payload` (e.g. `dict`) is accepted at construction, queue dedup checks, and `item_done` tracking because `hash(self.id)` is always hashable regardless of `payload` type." This absorbs the spec's "The `payload` field SHALL NOT participate in `__eq__` or `__hash__`; therefore an unhashable `payload` (e.g. a `dict`) SHALL be accepted at construction and during enqueue/get/item_done operations" sentence (relocated from `openspec/specs/testing-unit/spec.md` UniqueQueue requirement body).
- [x] 2.2 Add a single `# INVARIANTS: ...` line inside the `CLASS_UniqueQueue` region, between the existing `# PURPOSE: ...` line and the `class UniqueQueue(asyncio.Queue, Generic[TUMsgId, TUMsgPayload]):` line. Text: "Dedup is keyed on `UMessage.id` (via `UMessage.__eq__` / `__hash__`); two messages with equal `id` are duplicates regardless of `payload`. `_put_lock` serializes the check-then-enqueue step so concurrent `put` calls on a full queue cannot both enqueue the same item." This absorbs the spec's "Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two `UMessage` instances with equal `id` SHALL be treated as duplicates regardless of their `payload`." sentence (relocated from the same UniqueQueue requirement body). Note: the `MODULE_CONTRACT` already carries a higher-level `INVARIANTS` line "Dedup is by message ID, not payload — two messages with same ID but different payloads are treated as duplicates." — leave it as-is; the class-level `INVARIANTS` is more precise (mentions `_put_lock`).
- [x] 2.3 Add a single `# INVARIANTS: ...` line inside the `METHOD_put` region, between the existing `# PURPOSE: ...` line and the `async def put(...)` line. Text: "Holds `_put_lock` across the check-then-enqueue step; re-checks `_queue` and `_done_pending` membership after acquiring the lock to close the check-then-act race a blocking `super().put()` creates on a full queue." This captures the contract the `Scenario: UniqueQueue deduplicates under concurrent put on a full queue` asserts.
- [x] 2.4 DO NOT touch the existing `BLOCK_define_id_only_equality` region inside `CLASS_UMessage` — it is correctly placed (inside the enclosing `CLASS_*`) and its content is unchanged.
- [x] 2.5 DO NOT add new `METHOD_*` / `FUNC_*` regions for the trivial methods (`_get`, `get`, `task_done`, `item_done`, `psize`, `__init__`). They are one-to-three line operations that the GRACE proportional rule explicitly excludes ("Do not mark up trivial code: private one-liners, getters/setters, obvious operations"). The single `METHOD_put` region is kept because `put` carries non-trivial concurrency logic.
- [x] 2.6 DO NOT add `RATIONALE` to any region in `queue.py`. The relocated dedup content answers "what always holds?" (invariant-shaped), not "why is this shaped this way?" (rationale-shaped). Adding `RATIONALE` here would violate the closed-set rule (RATIONALE is Q/A format only) — the prior scrapped attempt failed precisely because RATIONALE was used as a junk drawer.
- [x] 2.7 Verify `uv run ruff check yascheduler/application/queue.py` and `uv run ruff format --check yascheduler/application/queue.py` pass; `uv run pytest -m unit tests/unit/test_queue.py` is green (the dedup behavior is unchanged; only comment enrichment).

## 3. End-to-end verify

- [x] 3.1 Manual scan: every `# region CLASS_*`, `FUNC_*`, `METHOD_*`, `BLOCK_*`, and `MODULE_CONTRACT` in `yascheduler/application/queue.py` has a paired `# endregion` and wraps the entire entity (no orphaned trailing code outside the region; no region closes before its entity ends; nested `METHOD_*` / `BLOCK_*` regions live INSIDE their enclosing `CLASS_*`; the `CLASS_*` `# endregion` comes AFTER the last nested `# endregion`). The three new `# INVARIANTS:` lines sit INSIDE the contract block (between `# PURPOSE:` and the first code line of the entity), NOT after the `# endregion` marker.
- [x] 3.2 Manual scan: no invented GRACE field names anywhere in `yascheduler/application/queue.py` — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` / `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`. Specifically, NO `SHALL NOT:` field, NO `EFFECTS:` field, NO `RAISES:` field, NO `EXAMPLES:` field anywhere. The three new lines are all `# INVARIANTS:` — verify each.
- [x] 3.3 Manual scan: every `PURPOSE` field in `queue.py` answers WHY, not WHAT. Spot-check: `MODULE_CONTRACT` ("Ensure each message ID is processed at most once per lifecycle so producer-consumer loops never double-process a task event"), `CLASS_UMessage` ("Enable UniqueQueue deduplication by identity — decouple message payload from identity..."), `CLASS_UniqueQueue` ("Prevent the daemon from processing the same task event twice across overlapping producer-consumer cycles"), `METHOD_put` ("Guarantee at-most-once delivery per message ID — skip duplicates already queued or processed so subsequent producer cycles do not re-enqueue the same event"), `BLOCK_define_id_only_equality` (no `PURPOSE` field — `BLOCK_*` regions take no fields per the GRACE spec). All five are WHY-shaped and stay unchanged.
- [x] 3.4 Manual scan: every `INVARIANTS` field in `queue.py` states conditions/contracts that ALWAYS hold (not rationale, not purpose, not free-form prose). Spot-check the three new lines: `CLASS_UMessage` INVARIANTS ("`__eq__` and `__hash__` consult `id` only..."), `CLASS_UniqueQueue` INVARIANTS ("Dedup is keyed on `UMessage.id`..."), `METHOD_put` INVARIANTS ("Holds `_put_lock` across the check-then-enqueue step..."). All three are positive-contract invariants.
- [x] 3.5 Manual scan: the trimmed `openspec/specs/testing-unit/spec.md` carries zero `SHALL NOT` / `shall not` / "SHALL NOT retain" / "SHALL NOT participate" / "SHALL NOT access" / "no `TaskContext` wrapper" / "no `context=` kwarg" / "`MachineOperations` Protocol is removed" / "M-ID validity and factory-only binding" / "synthetic-violation meta-tests specific to those removed guards" instances in requirement bodies. All 6 enumerated in `proposal.md` Why § 1 are gone.
- [x] 3.6 Manual scan: the trimmed `openspec/specs/testing-unit/spec.md` carries zero duplicate-of-scenario implementation prose in requirement bodies — verify the 4 cases enumerated in `proposal.md` Why § 2 are gone: (a) no "`queue_submit_task_async` MUST call `make_cli_deps(config).submit(label, metadata, engine_name)` and return its result" verbatim (the scenario asserts the call shape); (b) no "Orchestrator initialization creates 4 `UniqueQueue` instances with correct names and config-derived maxsizes, `start()` creates background tasks, `stop()` cancels tasks and cleans up, cancellation propagates to producer-consumer loops, and concurrency limits are passed as `workers_num`." enumeration (the orchestrator spec owns this); (c) no "Tests SHALL construct the client with a `FakeCLIDeps`-returning `deps_factory` whose `uow_factory()` returns a `FakeUnitOfWork` carrying a `FakeTaskRepository`." fixture-construction guidance; (d) no "`WebhookPayload` SHALL hold `task_id`, `status`, and `custom_params` fields. Default `custom_params` is empty dict." field-shape restatement (the scenario asserts the default; `CLASS_WebhookPayload` INVARIANTS in `yascheduler/infra/notifier/webhook.py` already states it).
- [x] 3.7 Manual scan: the trimmed `openspec/specs/testing-unit/spec.md` carries zero domain-contract restatements duplicating other specs — verify the 6 cases enumerated in `proposal.md` Why § 3 are gone or summarized: (a) no `Task.error` column-format enumeration (owned by `domain-entities` spec); (b) no exception-class enumeration (owned by `domain-exceptions` spec); (c) no use-case branch enumeration (owned by `use-cases` spec); (d) no orchestrator initialization detail (owned by `orchestrator` spec); (e) no DI factory enumeration (owned by `dependency-injection` spec); (f) no config value-object frozen / no-parser-methods enumeration (owned by `config-value-objects` spec). Each requirement body now summarizes the test surface in one or two sentences and points at the scenarios for the observable contracts.
- [x] 3.8 Manual scan: the `### Requirement: Shared test fixtures` block is GONE from `openspec/specs/testing-unit/spec.md` (requirement header, body, and the `#### Scenario: Mock factories provided for remote machine and clouds` block). Confirmed via `grep -c "Shared test fixtures" openspec/specs/testing-unit/spec.md` returns 0.
- [x] 3.9 `openspec validate --all --json` passes (exit 0); the trimmed `testing-unit` spec validates AND the change `testing-unit-spec-trim` validates AND no other spec regresses.
- [x] 3.10 `uv run pytest -m unit` — all unit tests pass (no behavior changed). The `tests/fixtures/mock_remote_machine.py` / `tests/fixtures/mock_clouds.py` files do not exist, so no test imports them — removing the phantom requirement does not break any test. Spot-check the directly-affected test files: `tests/unit/test_queue.py` (queue dedup), `tests/unit/test_log_scope_discipline.py` (logging guards).
- [x] 3.11 `uv run ruff check .` and `uv run ruff format --check .` pass on all changed files.
- [x] 3.12 `uv run lint-imports` passes (no new imports introduced; comment-only edits).
- [x] 3.13 Confirm no public-surface change: no CLI command, console_script, INI config key, DB schema, public API, log-format, pytest marker, or test-file structure change in the diff. The diff is `# region` / `# endregion` markup enrichment (3 `INVARIANTS` lines inside existing regions on `queue.py`) + spec text trim (18 MODIFIED requirements with verbatim scenarios, 1 REMOVED requirement and its phantom scenario) only.
