## proposal Round 1 — 2026-06-11 14:30

### 🔴 Issues

- **Incorrect file reference in Impact section**: "Modified: `scheduler.py` — `do_task_webhook()` method removed." The `do_task_webhook` / `_do_task_webhook` method lives in `application/orchestrator.py` (line 316), not `scheduler.py`. There is no `do_task_webhook` in `scheduler.py`. This misleads implementers to the wrong file. The What Changes section also says "Remove all `do_task_webhook()` calls from scheduler.py/use cases" — same error.

- **Frozen dataclass design tension unaddressed**: `Task` is a `frozen=True` dataclass (line 146, `domain/model.py`). The proposal says it gains `record_event()` and `pull_events()` methods for mutable event accumulation. A frozen dataclass forbids instance attribute mutation — storing a mutable event list requires a specific design choice (e.g., `__dict__` override, class-level thread-local storage, a mutable wrapper field, or switching to `frozen=False`). This is a non-trivial implementation decision that the proposal should acknowledge and resolve.

- **`TaskAbandoned` event has no corresponding Task lifecycle method**: The proposal lists five event types including `TaskAbandoned`, but `Task` has no `abandon()` method. The Modified Capabilities section says `task_consumer_consumer` records `TaskAbandoned` — but it's unclear what triggers this event on the aggregate or whether a new `Task.abandon()` transition method is needed. This should be made explicit.

### 🟡 Suggestions

- **Add a Non-Goals section**: The explore phase explicitly rejected event sourcing/CQRS and external message brokers. Stating these as non-goals would prevent scope creep and set clear boundaries for implementers.

- **Specify test file locations**: The `testing-unit` capability mentions "New unit tests for events, message bus, webhook handler, and updated UoW event dispatch" but doesn't name the test files. Specifying whether these go in a single `tests/unit/test_domain_events.py` or multiple files would help task planning.

- **Clarify `submit_task` additive behavior**: The proposal correctly notes `submit_task` has no current webhook calls and will gain `TaskCreated` recording. This is additive behavior that changes observable system behavior (webhook will now fire on task creation where it didn't before). Worth flagging in Impact as a behavioral change.

- **Mention `domain/__init__.py` update**: Adding `domain/events.py` likely requires updating `domain/__init__.py` to export the new event types. Not critical but worth listing.

- **Consider event for `Task.reject`**: The Task model has a `reject()` lifecycle method (line 237) used when a TO_DO task is rejected (e.g., unsupported engine). This seems like a significant lifecycle transition that should emit an event, but no `TaskRejected` event is listed.

### ✅ Strengths

- Clear problem statement: the inline webhook coupling is well-described with concrete bug class (side effects before commit confirmation).
- Event types map to meaningful Task lifecycle transitions, not arbitrary implementation details.
- Post-commit dispatch constraint is clearly stated and well-motivated.
- Modified capabilities list is comprehensive — touches UoW, entities, use cases, orchestrator, and tests.
- No new dependencies — correctly leverages existing `aiohttp`.
- Knowledge graph update acknowledged.
- Explore-phase decisions faithfully captured: aggregate-level recording, post-commit dispatch, in-process message bus.

### Verdict: FAIL

## proposal Round 4 — 2026-06-11 19:30

### 🔴 Fixed
- **`webhook_url` and `webhook_custom_params` moved to `DomainEvent` base**: Design Round 2 suggestion ("Webhook URL resolution unclear for non-TaskCreated events") fully resolved. proposal.md lines 39–40 and 54–55 describe base-class placement and source (`task.context`). design.md D1b (lines 42–46, 79–88) defines both fields on `DomainEvent` with rationale. D4 (lines 153–180) handler uses `event.webhook_url` directly with early-return on None, all branches use `event.webhook_custom_params`. D7 (lines 247–255) mapping table updated — all 6 constructor calls include `webhook_url, webhook_custom_params`, plus prose note at line 254–255 that they're populated from `task.context` at recording time. Three-way consistency between proposal, D1b, and D7 confirmed.

### 🔴 Outstanding
- None.

### 🟡 Suggestions
- **D9/D10 abbreviated constructor calls inconsistent with D1b**: D9 line 276 shows `TaskAbandoned(task_id, node_ip)` — missing `webhook_url` and `webhook_custom_params` which are required positional args on `DomainEvent` base (D1b). D10 lines 291–292 show `TaskFailed(reason="unsupported engine")` — missing `task_id`, `webhook_url`, `webhook_custom_params`. These snippets would fail at runtime. D7 has the canonical full signatures, so an implementer cross-referencing would get it right, but D9/D10 should either show full constructor args or use `...` to indicate omitted inherited fields. Non-blocking — D7 is the authoritative mapping.
- **Test file locations still unspecified**: Carried from Rounds 2–3. Non-blocking.

### Verdict: PASS

## design Round 2 — 2026-06-11 18:00

### 🔴 Fixed (from Round 1)

- **Use-case-to-event mapping absent**: D7 now provides a complete 6-row table mapping every use-case location to its event: submit_task→TaskCreated, allocate_task._allocate_free_machine→TaskAllocated, allocate_task._validate_engine→TaskFailed, consume_task→TaskCompleted, consume_task→TaskFailed, orchestrator._task_consumer_consumer→TaskAbandoned. All entries match the proposal. Resolved.

- **Webhook handler signature contradicts MessageBus dispatch contract**: D4 now shows `functools.partial(webhook_handler, http=session)` at registration time. The partial pre-binds the `http` keyword argument, so `dispatch()` calls the resulting callable with only `event`. The 2-arg function signature and 1-arg dispatch call are now compatible. Resolved.

- **Modified files from proposal Impact not covered by design decisions**: Three new decisions cover all four missing files: D9 (orchestrator.py — remove `_do_task_webhook`, remove `do_task_webhook` parameter, record TaskAbandoned, remove webhook_sem/http session management), D10 (submit_task.py, allocate_task.py, consume_task.py — per-use-case event recording details), D11 (domain/__init__.py — export event types and Event union). Resolved.

- **D6 rewording**: "Empty events tuple is a valid initial state" replaces misleading "events optional during transition." Matches the all-at-once conversion strategy in D7. Resolved.

### 🔴 Outstanding

- None.

### 🟡 Suggestions

- **Webhook URL resolution unclear for non-TaskCreated events**: D4 shows `_send_webhook(event.task_id, ..., status, http)` with `...` placeholders for the webhook URL in all branches except `TaskCreated`. Only `TaskCreated` carries `webhook_url` in its fields (D1b). The design doesn't explain how the handler obtains `webhook_url` for TaskAllocated/TaskCompleted/TaskFailed/TaskAbandoned. Options: (a) include `webhook_url` in every event type, (b) have the handler query a repository. The implementer needs a concrete resolution — consider adding this to D4 or D1b.

- **Test file locations still unspecified**: Carried from proposal Rounds 2–3 and design Round 1. Non-blocking — resolvable during task planning.

### Verdict: PASS

## proposal Round 2 — 2026-06-11 15:00

### ✅ Fixed (from Round 1)

- **Incorrect file reference**: All references in proposal.md now correctly point to `application/orchestrator.py`. Impact section lists each modified file individually. The sole remaining `scheduler.py` mention (line 4, "Why" section) is historical context ("Phase 3 extracted use cases from `scheduler.py`") — factually correct, not an implementation reference. Resolved.

- **Frozen dataclass design tension**: Proposal now specifies immutable approach: `_events: tuple[DomainEvent, ...]` field, `record_event()` returns new Task via `dataclasses.replace()`, `pull_events()` returns `(new_task, collected_events)`. Task remains `frozen=True`. No mutation, no `__dict__` hacks. Clean design. Resolved.

- **`TaskAbandoned` with no Task lifecycle method**: Proposal explicitly states TaskAbandoned is recorded at the use-case level in orchestrator's `_task_consumer_consumer` after `task.fail()` — not a Task aggregate method. The abandon semantics belong to the orchestrator. Made clear in both What Changes and Modified Capabilities. Resolved.

### 🟡 Addressed Suggestions

- **Non-Goals section added**: Explicitly excludes event sourcing/CQRS, external brokers, and node lifecycle events. Good.
- **`domain/__init__.py` listed in Impact**: Added to modified files.
- **`submit_task` behavioral change flagged**: Clearly noted in What Changes, Modified Capabilities, and Impact as a behavioural change.

### 🟡 Outstanding Suggestions

- **Specify test file locations**: The `testing-unit` capability still doesn't name test files. Non-blocking — can be resolved during task planning.
- **Consider `TaskRejected` event**: `Task.reject()` is a lifecycle transition not covered by any event. Non-blocking — can be added in a follow-up change.
- **`tasks.md` and `design.md` still reference `scheduler.py`**: Tasks 5.5–5.7 in `tasks.md` say "Remove `do_task_webhook()` method from scheduler.py" and design.md line 13 says "Remove `do_task_webhook()` from `scheduler.py`". These are downstream artifacts that will mislead implementers. Should be fixed when tasks/design are updated, but not a proposal-level issue.

### 🔴 Outstanding

- None.

### Verdict: PASS

## proposal Round 3 — 2026-06-11 16:30

### 🔴 Fixed
- **`Task.reject()` call-site covered**: Round 2 flagged `Task.reject()` as a lifecycle transition with no corresponding event. Investigation revealed `_validate_engine` in `allocate_task.py:53` calls `do_task_webhook` after `task.reject("unsupported engine")` — this call-site was missing from the proposal. Now explicitly addressed: `_validate_engine` records `TaskFailed(reason="unsupported engine")` instead of calling `do_task_webhook`. Decision: no separate `TaskRejected` type; rejection is a failure during validation. All three sections (What Changes, Modified Capabilities, Impact) updated consistently.

### 🔴 Outstanding
- None.

### 🟡 Suggestions
- **Test file locations still unspecified**: Carried from Round 2. Non-blocking — resolvable during task planning.
- **`tasks.md` / `design.md` stale `scheduler.py` references**: Carried from Round 2. Non-blocking — downstream artifacts, not proposal-level.

### Verdict: PASS

## design Round 1 — 2026-06-11 17:00

### 🔴 Issues

- **Use-case-to-event mapping absent**: The proposal explicitly enumerates which use cases record which events (`submit_task` → `TaskCreated`, `allocate_task` → `TaskAllocated` + `_validate_engine` → `TaskFailed`, `consume_task` → `TaskCompleted`/`TaskFailed`, `orchestrator._task_consumer_consumer` → `TaskAbandoned`). The design provides no equivalent mapping. D2 shows the general `record_event` flow, D6 mentions events are optional, but an implementer cannot determine which events to record in which use cases without cross-referencing the proposal. This is core design information — the design must stand alone for implementation. Add a decision (or extend D2) that enumerates the use-case → event mapping.

- **Webhook handler signature contradicts MessageBus dispatch contract**: D3 dispatches events as `await handler(event)` (single argument). D4 defines `webhook_handler(event: DomainEvent, http: aiohttp.ClientSession)` (two arguments). These are incompatible — registering `webhook_handler` with `MessageBus.register(TaskCreated, webhook_handler)` would fail at dispatch time. The design must resolve this: either show a closure/factory that captures the session (`lambda e: webhook_handler(e, session)`), make the handler a class with `__call__`, or restructure the signature to take only the event and obtain the session via dependency injection.

- **Modified files from proposal Impact not covered by design decisions**: The proposal lists four modified files with no corresponding design decisions:
  - `application/orchestrator.py` — remove `_do_task_webhook()`, remove `do_task_webhook` parameter from `_allocator_consumer` and `_task_consumer_consumer`, record `TaskAbandoned` event. The Goals section mentions removing the method but no decision describes the orchestrator changes.
  - `application/submit_task.py` — record `TaskCreated` (additive behavioral change). Not mentioned anywhere in design.
  - `application/consume_task.py` — record `TaskCompleted` or `TaskFailed`. Not mentioned anywhere in design.
  - `domain/__init__.py` — export event types. Not mentioned anywhere in design.
  Each of these needs a design decision or explicit coverage in an existing decision.

### 🟡 Suggestions

- **D4 code snippet incomplete**: The `webhook_handler` snippet shows `...` placeholders for `TaskFailed` and `TaskAbandoned` branches. Since the event-to-status mapping is the handler's core logic, showing all five branches (including `TaskFailed` → DONE+error and `TaskAbandoned` → which status?) would remove ambiguity.

- **D5 doesn't show `save()` modification**: The design says "`tasks.save(task)` appends to `_saved_tasks`" but doesn't show the code. The `PostgresTaskRepository.save()` method needs modification to support this — a code snippet would clarify whether tracking happens in the repository or the UoW wrapper.

- **D6 "Events optional during transition" is misleading**: The proposal converts ALL use cases in this change — there is no transition period. D6 describes a structural property (empty `_events` tuple is valid) rather than a migration strategy. Consider rewording to clarify this is an invariant, not a phased rollout plan.

- **Test file locations still unspecified**: Carried from proposal Rounds 2–3. Non-blocking but resolvable here.

### ✅ Strengths

- **Immutable tuple approach is consistent**: D2, D5, D6, and Risks all describe the same frozen-dataclass-compatible pattern — `_events: tuple[DomainEvent, ...]`, `replace()` for mutation, `pull_events()` for extraction. No contradictions.

- **D7 aligns precisely with proposal's _validate_engine decision**: `TaskFailed(reason)` for unsupported engine, no separate `TaskRejected` type. Rationale (reject is a failure during validation) matches proposal exactly.

- **D1 layering argument is sound**: Events in `domain/` avoids upward dependency from `domain/model.py` into application layer. Clean hexagonal boundary.

- **D5 post-commit dispatch is correct**: Events fire only after `_conn.commit()` succeeds. The `rollback()` path clears `_saved_tasks` — no events leak on failure.

- **Code snippets are syntactically valid Python**: All dataclass definitions, method signatures, and Protocol declarations are correct.

- **Risks section is honest and complete**: Handler failure, process crash between commit and dispatch, and aggregate replay limitations are all acknowledged with clear rationale for why they're acceptable for v1.

### Verdict: FAIL

## design Round 4 — 2026-06-11 21:00

### 🟡 Addressed (from previous rounds)
 - **D9/D10 full constructor calls**: Both decisions now show complete event constructor invocations with all required fields (`task_id`, `webhook_url`, `webhook_custom_params`, plus type-specific fields). D9 line 288-290: `TaskAbandoned(task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, node_ip=ip)`. D10 lines 298-324: all five event recordings (`TaskCreated`, `TaskAllocated`, `TaskFailed` ×2, `TaskCompleted`) include full keyword arguments sourced from `task.context`. Consistent with D1b base-class definition and D7 mapping table. No decision-level changes — purely declarative expansion of existing code snippets.
 - **D5 save() snippet added**: D5 now includes `PostgresTaskRepository` class (lines 239-247) showing `__init__(self, conn, saved_tasks: list[Task])` and `save()` method with `self._saved_tasks.append(task)`. Clarifies that the UoW passes the tracking list to the repository at construction time. No decision-level changes — supplementary code illustration.

### 🔴 Outstanding
 - None.

### 🟡 Suggestions
- **Test file locations still unspecified**: Carried from all previous rounds. Non-blocking — resolvable during task planning.

### Verdict: PASS

## specs Round 1 — 2026-06-11 22:00

### 🔴 Issues

- **No spec coverage for D7 (use-case→event mapping)**: The design provides a 6-row table mapping every use-case location to its event. The three spec files contain zero requirements or scenarios covering which use cases record which events. There is no scenario for `submit_task` recording `TaskCreated`, `allocate_task._allocate_free_machine` recording `TaskAllocated`, `allocate_task._validate_engine` recording `TaskFailed`, `consume_task` recording `TaskCompleted`/`TaskFailed`, or `orchestrator._task_consumer_consumer` recording `TaskAbandoned`. These are the core behavioral changes of the entire change — the event types and bus are infrastructure; the use-case recordings are the purpose. The specs must include requirements (either under `message-bus/spec.md` or a new `use-cases/spec.md`) with scenarios that an implementer can test against. Without them, D7 is unverifiable at the spec level.

- **No spec coverage for D9 (orchestrator cleanup) and D10 (use case changes)**: D9 specifies removing `_do_task_webhook()`, removing `do_task_webhook` parameter from orchestrator call-sites, and recording `TaskAbandoned` in `_task_consumer_consumer`. D10 specifies per-use-case event recording with full constructor signatures. Neither has any corresponding spec requirement. The proposal lists `use-cases` and `orchestrator` as modified capabilities but no delta spec exists for either. An implementer following only specs would not know these files need modification. Add requirements under `message-bus/spec.md` (or separate capability specs) covering: (a) removal of `_do_task_webhook` and `do_task_webhook` parameter, (b) event recording in each use case.

- **D6 (empty tuple as valid initial state) has no scenario**: The design explicitly calls out that `_events=()` is a valid default. There is no scenario testing `pull_events()` on a Task with no recorded events (should return `(task, ())`), nor that a Task constructed without events has `_events == ()`. Add a scenario under "Events collected from aggregates via immutable tuple" in `message-bus/spec.md`.

- **D8 (TaskFailed for rejection, no TaskRejected) not explicit**: The design makes a deliberate choice that `_validate_engine` records `TaskFailed` instead of a `TaskRejected` type. While `TaskFailed` is defined in `domain-events/spec.md`, no scenario links the rejection use case to `TaskFailed`. This means the spec doesn't prevent a future implementer from introducing `TaskRejected` as a separate type. Add a requirement/scenario stating that engine validation failure records `TaskFailed(reason)` and no separate rejection event type exists.

### 🟡 Suggestions

- **Inconsistent scenario detail in webhook-handler**: The `TaskCreated` scenario mentions "custom_params in payload" explicitly, but `TaskAllocated`, `TaskCompleted`, `TaskFailed`, and `TaskAbandoned` scenarios only mention the status code. Either all scenarios should mention custom_params or the general requirement should be sufficient and the TaskCreated scenario should match the others' conciseness. Minor inconsistency.

- **No scenario for `collect_events()` with multiple aggregates**: The "Dispatch after commit via UoW" scenario is singular — it doesn't test that `collect_events()` correctly iterates over multiple saved aggregates. A scenario like "WHEN two tasks are saved in one UoW, THEN events from both are collected and dispatched" would strengthen coverage.

- **Test file locations still unspecified**: Carried from every previous round since proposal Round 2. Non-blocking but 7 rounds of carry-forward suggests it should be resolved.

### ✅ Strengths

- **Event type definitions are complete and testable**: All five event types have frozen dataclass definitions with typed fields, concrete instantiation scenarios with literal values, and attribute access assertions. Directly translatable to unit tests.

- **Webhook status mapping is unambiguous**: Every event type has a clear status mapping (TaskCreated→TO_DO, TaskAllocated→RUNNING, TaskCompleted→DONE, TaskFailed→DONE+error, TaskAbandoned→DONE+error). The handler spec covers all five branches plus edge cases (no URL, HTTP failure).

- **Message bus core mechanics well-specified**: Registration, dispatch, multi-handler, functools.partial, and import path all have concrete scenarios. The `functools.partial` scenario exactly matches the D4 design code snippet.

- **UoW event lifecycle is clear**: Post-commit dispatch, rollback discarding, save() tracking, and immutable aggregate pattern are all specified with WHEN/THEN scenarios.

- **Spec organization aligns with capability boundaries**: `domain-events` (pure event types), `message-bus` (dispatch infrastructure), `webhook-handler` (adapter) — clean separation of concerns at the spec level.

### Verdict: FAIL


## design Round 3 — 2026-06-11 20:00

### 🔴 Fixed
- **webhook_url/webhook_custom_params on DomainEvent base (from proposal Round 4)**: D1b (lines 42-46) defines both fields on `DomainEvent` with types `str | None` and `dict[str, object]`. Rationale block (lines 79-88) explains base-class placement vs query-repository and per-subclass-duplication alternatives. D4 (lines 153-170) handler accesses `event.webhook_url` directly with early-return on None; all 5 branches pass `event.webhook_custom_params`. D7 (lines 247-253) mapping table shows `webhook_url, webhook_custom_params` in all 6 constructor signatures; prose at lines 254-255 confirms population from `task.context`. Three-way consistency between D1b, D4, D7 confirmed.

### 🔴 Outstanding
- None.

### 🟡 Suggestions
- **D9/D10 abbreviated constructor calls still inconsistent with D1b** (carried from proposal Round 4): D9 line 276 shows `TaskAbandoned(task_id, node_ip)` — missing `webhook_url` and `webhook_custom_params` which are required positional args on `DomainEvent` base (D1b). D10 lines 291-292 show `TaskFailed(reason="unsupported engine")` — missing `task_id`, `webhook_url`, `webhook_custom_params`. These snippets would fail at runtime. D7 has canonical full signatures. Recommend either showing full args or adding an explicit `# abbreviated — see D7 for full signature` note. Non-blocking.
- **Test file locations still unspecified**: Carried from all previous rounds. Non-blocking — resolvable during task planning.

### Verdict: PASS

## specs Round 2 — 2026-06-11 23:00

### 🔴 Fixed (from Round 1)

 - **D7 use-case→event mapping now has full spec coverage**: `message-bus/spec.md` lines 86–123 add "Use-case-to-event mapping" requirement with a 6-row table matching D7 exactly (submit_task→TaskCreated, allocate_task._allocate_free_machine→TaskAllocated, allocate_task._validate_engine→TaskFailed, consume_task→TaskCompleted, consume_task→TaskFailed, orchestrator._task_consumer_consumer→TaskAbandoned) plus 6 concrete WHEN/THEN scenarios. Table entries match design.md D7 lines 257–264 row-for-row. Resolved.

 - **D9/D10 orchestrator cleanup + use case changes now covered**: `message-bus/spec.md` lines 125–139 add "Use case and orchestrator cleanup" requirement with 3 scenarios: (a) `do_task_webhook` parameter removed from `allocate_task()` and `consume_task()`, (b) `_do_task_webhook()` method removed from `Orchestrator`, no parameter passed to consumer call-sites, (c) `submit_task` gains `TaskCreated` event recording with behavioural-change note. Covers D9 (orchestrator method/parameter removal) and D10 (per-use-case changes beyond event recording, which D7 scenarios already cover). Resolved.

 - **D6 empty-tuple initial state now has a scenario**: `message-bus/spec.md` lines 63–65: "pull_events on Task with no events" scenario — WHEN `pull_events()` called on Task with `_events=()`, THEN returns `(same_task, ())`, no dispatch. Resolved.

 - **D8 TaskFailed for rejection now explicit**: `message-bus/spec.md` lines 109–111: "_validate_engine records TaskFailed on unsupported engine" scenario explicitly states `TaskFailed(reason="unsupported engine")` is recorded and includes normative statement "No separate `TaskRejected` event type SHALL exist — rejection during validation is a failure." Prevents future introduction of `TaskRejected`. Resolved.

### 🔴 Outstanding

 - None.

### 🟡 Suggestions

 - **"same_task" wording in pull_events empty-tuple scenario**: `message-bus/spec.md` line 65 says `pull_events()` returns `(same_task, ())`. Per D2, `pull_events()` calls `replace(self, _events=())` which always creates a new instance — never the same object. For the empty-tuple case the result is structurally identical but not referentially identical. Consider wording as `(new_task_with_empty_events, ())` for consistency with the non-empty scenario at line 61, or note that "same_task" means structurally equivalent. Minor — intent is clear.

 - **Inconsistent scenario detail in webhook-handler**: `webhook-handler/spec.md` TaskCreated scenario (line 13) mentions "custom_params in payload" explicitly; TaskAllocated through TaskAbandoned scenarios only mention status code. Either all should mention custom_params or the general requirement (lines 8–9: "access webhook_url and webhook_custom_params from DomainEvent base") is sufficient and the TaskCreated scenario should match the others' conciseness. Carried from Round 1.

 - **No scenario for collect_events with multiple aggregates**: The "Dispatch after commit via UoW" requirement has only singular scenarios. A scenario like "WHEN two tasks are saved in one UoW, THEN events from both are collected and dispatched" would strengthen coverage. Carried from Round 1.

 - **Test file locations still unspecified**: Carried from every round since proposal Round 2 (9 rounds total). Non-blocking but long carry-forward suggests it should be resolved during task planning.

### Verdict: PASS

## tasks Round 1 — 2026-06-12 00:15

### 🔴 Issues

 - **Task 7.4 — `WebhookPayload` removal is factually wrong and adds undocumented scope**: Task 7.4 says "Remove `WebhookPayload` class from `application/orchestrator.py`" but `WebhookPayload` is NOT defined there. It is defined in `yascheduler/webhook.py` (line 29) as a frozen dataclass (`task_id`, `status`, `custom_params`). It is only **imported** in `application/orchestrator.py` (line 49: `from yascheduler.webhook import WebhookPayload`) and used at line 328 inside `_do_task_webhook`. Neither the proposal nor design mentions removing `WebhookPayload` at all — design D9 lists only `_do_task_webhook`, `do_task_webhook` parameter, `webhook_sem`, and `http` session as removals. Furthermore, `scheduler.py` re-exports it (line 40: `from .webhook import WebhookPayload as WebhookPayload`), indicating it may be part of the public interface (AGENTS.md lists `class Yascheduler` public API stability). A literal-minded implementer could remove the class from `yascheduler/webhook.py` and break the re-export. Task 7.4 should either: (a) be reworded to "Remove unused `WebhookPayload` import from `application/orchestrator.py`" (cleanup after removing `_do_task_webhook`), or (b) if the intent is to remove the class entirely, that decision must be added to the proposal/design first — and the new webhook handler's payload construction strategy (does it reuse `WebhookPayload` or build a dict inline?) must be clarified, since design D4's `_send_webhook` helper doesn't reference `WebhookPayload`.

### 🟡 Suggestions

 - **Task 4.3 missing file path for `PostgresTaskRepository`**: The task says "Update `PostgresTaskRepository.__init__`" without specifying the file. `PostgresTaskRepository` lives in `adapters/persistence/postgres.py` (line 69), separate from `PostgresUnitOfWork` which is in `adapters/persistence/postgres_uow.py` (line 48). An implementer might search in the wrong file. Recommend adding the file path.

 - **No explicit test for `functools.partial` registration scenario**: The message-bus spec has a scenario "Handler registered via functools.partial" (spec lines 28–30). Task 3.6 covers "dispatch to single handler, event with no handlers silently ignored, multiple handlers per event type" but does not include a test verifying that a `functools.partial`-wrapped handler receives only the event at dispatch time. This is the DI wiring contract — worth an explicit unit test in `tests/unit/test_message_bus.py` or `tests/unit/test_webhook_handler.py`.

 - **HTTP session lifecycle unaddressed after orchestrator removal**: Task 7.5 removes `_http` session management from the orchestrator. Task 4.8 creates the session in DI via `functools.partial(webhook_handler, http=session)`. But no task addresses session lifecycle — who creates the `aiohttp.ClientSession` (async context), and who closes it on shutdown? The orchestrator currently creates it at line 677 (likely in `start()`) and closes at lines 720–722 (likely in `stop()`). After removal, the DI factory must own creation and the shutdown path must close it. Recommend a task or note clarifying session lifecycle ownership.

 - **Task 7.5 parenthetical "(moved to webhook handler)" slightly misleading**: The HTTP session is not moved to `adapters/notifier/webhook.py` — it's created in DI (`di.py`) and passed via `functools.partial`. Only the semaphore (rate limiting) and retry logic move to the webhook handler module. The parenthetical could read "(retry logic and semaphore moved to webhook handler; session created in DI)".

 - **Task 8.4 `-k` filter may miss use case tests**: The filter `"event or message_bus or webhook"` would match tests in `test_domain_events.py`, `test_message_bus.py`, and `test_webhook_handler.py`. But characterization tests in `test_application_use_cases.py` (task 6.8) may have names like `test_submit_task_records_task_created` that don't contain "event", "message_bus", or "webhook". They'd be caught by the full suite in task 8.5, but task 8.4 claims to run "all tests pass" for the new test set. Consider broadening the filter or adding `or use_case` / `or records` to the pattern.

### ✅ Strengths

 - **Complete coverage of all 12 design decisions**: D1–D11 each map to specific tasks. D1b (base-class fields) → 1.1; D2 (immutable tuple) → 2.1–2.3; D3 (MessageBus) → 3.1–3.4; D4 (webhook handler + functools.partial) → 5.1–5.7, 4.8; D5 (UoW dispatch) → 4.1–4.7; D6 (empty tuple valid) → 2.5 test; D7 (use-case mapping) → 6.1, 6.3, 6.4, 6.6, 7.3; D8 (TaskFailed for rejection) → 6.4; D9 (orchestrator cleanup) → 7.1–7.5; D10 (use case changes) → 6.1–6.6; D11 (domain exports) → 1.8.

 - **All proposal Impact files covered**: Every file in the Impact section (new: events.py, message_bus.py, webhook.py; modified: model.py, uow.py, postgres_uow.py, orchestrator.py, allocate_task.py, consume_task.py, submit_task.py, __init__.py, knowledge-graph.xml) has corresponding tasks.

 - **Event constructor signatures in tasks match D9/D10 exactly**: Tasks 6.1, 6.3, 6.4, 7.3 all show full keyword arguments (`task_id=task.task_id, webhook_url=task.context.webhook_url, webhook_custom_params=task.context.webhook_custom_params, ...`) — consistent with the canonical D7 mapping and D1b base-class definition.

 - **Test file locations specified**: Resolves 9 rounds of carry-forward suggestion. Four explicit paths: `tests/unit/test_domain_events.py`, `tests/unit/test_message_bus.py`, `tests/unit/test_webhook_handler.py`, `tests/unit/test_application_use_cases.py`.

 - **Logical section ordering follows dependency chain**: Domain events (no deps) → Task aggregate (needs events) → Message bus (needs events) → UoW (needs bus + aggregate) → Webhook handler (needs events) → Use cases (needs events + aggregate) → Orchestrator (needs events + use case signatures) → Verification. No circular dependencies.

 - **Appropriate granularity**: All 46 tasks are focused, each ≤ 2 hours. No mega-tasks. Verification section (8.1–8.6) properly separates static checks, graph updates, spec validation, targeted tests, full suite, and smoke test.

 - **Status code mapping in task 5.4 matches spec exactly**: TaskCreated→TO_DO (0), TaskAllocated→RUNNING (1), TaskCompleted→DONE (2), TaskFailed→DONE (2) error, TaskAbandoned→DONE (2) error — identical to webhook-handler spec scenarios.

 - **Orchestrator cleanup properly separated into Section 7**: Keeps D9 changes (method/parameter removal, TaskAbandoned recording, session/semaphore removal) distinct from use case changes (Section 6), matching the design's D9 vs D10 split.

 - **Verification section comprehensive**: Includes `grace_check.py` (8.1), knowledge-graph.xml M-ID updates for all affected modules (8.2), `openspec validate` (8.3), targeted pytest (8.4), full regression suite (8.5), and end-to-end smoke test (8.6).

### Verdict: FAIL

## tasks Round 2 — 2026-06-12 00:45

### 🔴 Fixed (from Round 1)

 - **Task 7.4 WebhookPayload removal rewritten**: Now correctly targets only the unused import (`from yascheduler.webhook import WebhookPayload`) in `application/orchestrator.py`. Explicitly states the class in `yascheduler/webhook.py` stays — may be part of public interface (re-exported from `scheduler.py`). No longer risks breaking the public API.

 - **Task 4.3 file path added**: Now reads "Update `PostgresTaskRepository.__init__` in `adapters/persistence/postgres.py`" — disambiguates from `PostgresUnitOfWork` which lives in `adapters/persistence/postgres_uow.py`.

 - **Task 3.6 functools.partial test added**: Test scenario list now includes "`functools.partial`-wrapped handler receives only event at dispatch" — covers the DI wiring contract from message-bus spec scenario "Handler registered via functools.partial".

 - **Task 4.8 session lifecycle specified**: DI wiring task now says "create `aiohttp.ClientSession` (owned by DI, closed on shutdown)" — addresses creation and teardown ownership after removal from orchestrator.

 - **Task 7.5 parenthetical corrected**: Now reads "(retry logic and semaphore moved to webhook handler; session created and owned by DI)" — accurately distinguishes what moves to the handler module vs what moves to DI.

 - **Task 8.4 pytest filter broadened**: Filter now reads `"event or message_bus or webhook or use_case"` — catches characterization tests in `test_application_use_cases.py` (task 6.8) whose names may not contain "event"/"webhook".

### 🔴 Outstanding

 - None.

### 🟡 Suggestions

 - **Task 4.2 could also include file path for consistency**: Task 4.2 says "Update `PostgresUnitOfWork.__init__`" without a file path, while 4.3 now includes one. `PostgresUnitOfWork` lives in `adapters/persistence/postgres_uow.py` — adding the path would be consistent. Minor.

 - **Section ordering: task 4.8 references `webhook_handler` before Section 5 creates it**: Task 4.8 (DI wiring) registers handlers via `functools.partial(webhook_handler, http=session)`, but the webhook handler module (Section 5) hasn't been created yet. Implementers following section order would need to implement Section 5 first or know the handler signature from the design. Not blocking — the design provides the full signature, and tasks don't mandate strict sequential execution. Just noting the forward reference.

### Verdict: PASS

## tasks Round 3 — 2026-06-12 01:15

### 🟡 Addressed (from Round 2)
 - **Task 4.2 file path added**: Now reads "Update `PostgresUnitOfWork.__init__` in `adapters/persistence/postgres_uow.py`" — consistent with Task 4.3 which already included its file path. Declarative only, no decision-level change.
 - **Task 4.8 forward reference clarified**: Now includes "(see Section 5 for handler signature)" after the `functools.partial(webhook_handler, http=session)` clause — clarifies the forward reference to the webhook handler that Section 5 creates. Declarative only, no decision-level change.

### 🔴 Outstanding
 - None.

### 🟡 Suggestions
 - None.

### Verdict: PASS

## specs Round 3 — 2026-06-11 23:30

### 🟡 Addressed (from Round 2)
 - **"same_task" wording fixed in pull_events empty-tuple scenario**: `message-bus/spec.md` line 65 now uses `new_task_with_empty_events` — consistent with the non-empty scenario at line 61 and technically accurate per D2 (`replace()` always creates a new instance).
 - **"custom_params in payload" removed from TaskCreated webhook scenario**: `webhook-handler/spec.md` TaskCreated scenario (line 13) now matches the conciseness of all other scenarios — just status code. The general requirement at lines 8–9 already covers `webhook_custom_params` access from `DomainEvent` base.
 - **"Events from multiple aggregates dispatched in one commit" scenario added**: `message-bus/spec.md` lines 42–44 add a scenario: WHEN two tasks saved in one UoW with recorded events, THEN `collect_events()` pulls from both and all events dispatched in order. Purely declarative addition — no existing requirement changed.
 - **Test file locations**: Correctly deferred to task planning. Not a spec-level concern.

### 🔴 Outstanding
 - None.

### 🟡 Suggestions
 - None.

### Verdict: PASS

## implementation Round 1 — 2026-06-19 16:59

Scope: staged implementation of `domain-events` (29 files, +2243/-522) reviewed
against GRACE-lite methodology and the frozen proposal/design/specs/tasks.

Validation run:
- `python3 scripts/grace_check.py` → exit 0 (warnings only: func-size/block-size)
- `openspec validate --all --json` → 29/29 passed, exit 0
- `uv run ruff check .` → **exit 1 (TC001)** — BLOCKING
- `uv run ruff format --check .` → 124 files formatted, exit 0
- `uv run pytest -m unit` → 346 passed, exit 0
- `uv run pytest -m integration` → environment-blocked (testcontainers
  PermissionError/APIError on Docker socket in this sandbox); not a code
  regression — re-run in a Docker-enabled environment before archive.

### 🔴 Issues

 - **`uv run ruff check .` FAILS (exit 1) — TC001 in `yascheduler/domain/model.py:33`**.
   The new runtime import `from .events import DomainEvent` is flagged because
   `model.py` has `from __future__ import annotations`, so `DomainEvent` is only
   used in annotations (`_events: tuple[DomainEvent, ...]`,
   `record_event(self, event: DomainEvent)`, `pull_events` return type) and is
   never evaluated at runtime. AGENTS.md mandates `uv run ruff check .` must
   pass; this is a lint regression introduced by this change (the import is new).
   Fix: move `from .events import DomainEvent` into the existing
   `if TYPE_CHECKING:` block in `model.py` (ruff's suggested fix; safe because
   the symbol is annotation-only). Links: AGENTS.md "Static checks".

 - **`domain/__init__.py` emptied — contradicts D11 / task 1.8 and leaves the
   knowledge graph inaccurate (GRACE drift)**. D11 ("domain/__init__.py updated
   to export all event types and the Event union type alias from
   domain.events") and task 1.8 require the package to re-export events.
   Instead the file is now 0 bytes — all prior MODULE_CONTRACT / MODULE_MAP /
   CHANGE_SUMMARY markup deleted, no exports added. Meanwhile the KG delta
   (`docs/knowledge-graph.xml`) changed `M-DOMAIN` purpose to "re-exports
   domain events", `<depends>M-DOMAIN-EVENTS</depends>`, and added
   `<CrossLink from="M-DOMAIN" to="M-DOMAIN-EVENTS" relation="re-exports event
   types from domain package" />` — so the graph now claims a re-export
   relationship the code does not provide. This violates GRACE rules
   "Knowledge Graph Is Always Current" and "Never remove semantic markup
   anchors unless intentionally replacing them." No runtime break (nothing
   imports from the `yascheduler.domain` package; the spec only requires
   `yascheduler.domain.events`), but graph-vs-code drift is a GRACE integrity
   defect. Fix: either (a) add the D11 re-exports to `domain/__init__.py`
   (`from .events import DomainEvent, TaskCreated, ... , Event` + restore
   MODULE_CONTRACT markup), or (b) if intentionally not re-exporting, unfreeze
   D11/task 1.8 and correct the KG `M-DOMAIN` entry (revert purpose/depends and
   drop the CrossLink). The three artefacts must agree.

### 🟡 Suggestions

 - **UoW shared-list invariant breaks after `collect_events()`
   (`yascheduler/adapters/persistence/postgres_uow.py:183-191`)**.
   `collect_events()` does `self._saved_tasks = remaining`, but
   `PostgresTaskRepository` was given the *original* list at construction
   (`__aenter__` line 105-107) and still references it. After `collect_events`,
   `repo._saved_tasks` points at a list the UoW no longer reads. In the normal
   single-commit flow this is harmless (no `save()` after `commit()`), but if
   `save()` is ever called after `commit()` within the same `async with` block,
   those events are appended to a stale list and silently never dispatched.
   Fix: mutate in place to preserve the shared reference, e.g.
   `saved = list(self._saved_tasks); self._saved_tasks.clear();
   for t in saved: clean, evs = t.pull_events(); events.extend(evs);
   self._saved_tasks.append(clean)`. (The reassignment pattern is copied
   verbatim from design D5, so this is a latent design-level issue worth
   hardening at the implementation.)

 - **`webhook_handler` signature deviates from D4
   (`yascheduler/adapters/notifier/webhook.py:62-66`)**. D4 specifies
   `http: aiohttp.ClientSession` with only an `event.webhook_url is None`
   early-return. The implementation widens this to
   `http: aiohttp.ClientSession | None` and adds an `http is None` early-return.
   This extra guard exists to support the CLI no-op wiring in
   `di.py:204` (`partial(webhook_handler, http=None)`), but it is not covered by
   any webhook-handler spec scenario (all pass a real session) and silently
   swallows wiring bugs (a forgotten session → webhooks never sent, no error).
   If the `| None` is intentional, add a spec scenario or a note; otherwise,
   prefer having CLI wiring register no handler (or a dedicated no-op) instead
   of routing real events through a handler that silently drops them.

 - **GRACE-lite size limits exceeded on changed code** (grace_check warnings,
   non-fatal but flagged): `consume_task.py:_finalize_task` 76 lines with
   contract (limit 60) and `BLOCK_SET_STATUS` 55 lines (limit 50) — both grew
   from the event-recording added here; `di.py:make_daemon` 79 lines with
   contract (limit 60). AGENTS.md: "Exceed → evaluate splitting." Consider
   extracting the event-recording block in `_finalize_task` into a helper.

 - **Stray untracked files in repo root**: `1.input` (contents "boobs") and
   `TESTJOB` ("ENGINE=dummiest") — look like manual test artefacts. Remove or
   add to `.gitignore` so they are not accidentally committed.

 - **Unstaged `AGENTS.md` fix** (test command `uv run -m unit` →
   `uv run pytest -m unit`, plus reflowed text): a legitimate doc correction
   and exactly the command used in this review, but it is NOT staged with the
   change. Either stage it alongside this change or commit separately so it is
   not lost.

### ✅ Strengths

 - **D1–D11 all implemented and faithful to the frozen design**:
   `DomainEvent` base + 5 frozen subclasses with the exact typed fields from
   D1b; `Task._events: tuple[...]` + `record_event`/`pull_events` via
   `dataclasses.replace()` preserving `frozen=True` (D2); `MessageBus`
   registry + async dispatch (D3); webhook handler with correct status mapping
   (TO_DO/RUNNING/DONE/DONE+err/DONE+err) and `backoff.fibo(max_time=60)`
   retry + semaphore(10) (D4); post-commit dispatch with `rollback()` clearing
   `_saved_tasks` (D5); empty-tuple valid initial state (D6); all 6
   use-case→event recordings in D7 with full kwargs from `task.context`
   (submit_task→TaskCreated, _allocate_free_machine→TaskAllocated,
   _validate_engine→TaskFailed, consume_task→TaskCompleted/TaskFailed,
   _task_consumer_consumer→TaskAbandoned); D8 `TaskFailed` for rejection with
   no `TaskRejected`; D9 `_do_task_webhook` removed, `do_task_webhook`
   parameter dropped from both consumer call-sites, `webhook_sem`/HTTP creation
   removed from orchestrator; D10 per-use-case kwargs; event types importable
   from `yascheduler.domain.events`.

 - **Every WHEN/THEN in all three spec files is satisfiable by the
   implementation** — event construction + field access, status mapping
   (0/1/2), fibonacci retry, no-URL skip, error-logged-not-raised, post-commit
   dispatch, rollback discard, multi-aggregate collection, `pull_events`
   empty/non-empty, all 6 use-case mapping scenarios, and the import-path
   scenarios.

 - **Unit tests: 346 passed.** New `test_domain_events.py`,
   `test_message_bus.py`, `test_webhook_handler.py` plus characterization
   tests in `test_application_use_cases.py` (TestSubmitTaskEvents /
   TestAllocateTaskEvents / TestConsumeTaskEvents) and
   `test_application_orchestrator.py::TestOrchestratorTaskAbandoned` cover
   every D7 mapping. `test_message_bus.py` includes the spec's
   `functools.partial`-handler scenario and a multi-handler-failure-isolation
   test.

 - **Knowledge graph**: new M-DOMAIN-EVENTS, M-APPLICATION-MESSAGE-BUS,
   M-NOTIFIER, M-NOTIFIER-WEBHOOK added with correct type/status; annotations
   updated on M-DOMAIN-MODEL, M-APPLICATION-UOW, M-PERSISTENCE-UOW,
   M-APPLICATION-ORCHESTRATOR/ALLOCATE/CONSUME, M-DI; new CrossLinks for event
   dispatch wiring (UoW→MessageBus, UoW→DomainEvent, each use case→events,
   DI→MessageBus/Notifier). (Caveat: the M-DOMAIN entry itself is inaccurate —
   see 🔴 above.)

 - **GRACE-lite markup present on all 4 new files** (events.py, message_bus.py,
   notifier/__init__.py, notifier/webhook.py) with MODULE_CONTRACT/MODULE_MAP/
   CHANGE_SUMMARY; function contracts on `record_event`, `pull_events`,
   `MessageBus.register/dispatch`, `webhook_handler`, `_send_webhook`,
   `collect_events`, `publish_events`, `commit`, `rollback`; updated
   CHANGE_SUMMARY entries on all modified governed files.

 - **Frozen-artifact integrity holds**: the staged edits to proposal.md,
   design.md, specs/*/spec.md, tasks.md match the declarative additions
   recorded in the prior PASS rounds (full D9/D10 constructor kwargs, D5
   `save()` snippet, multi-aggregate scenario, `new_task_with_empty_events`
   wording, file-path clarifications, WebhookPayload-import-only rewording).
   No new decision-level change was snuck into a frozen artefact.

 - **Webhook retry/rate-limit semantics preserved** from the removed
   `_do_task_webhook` (fibonacci backoff `max_time=60`, concurrency semaphore).

### Verdict: FAIL

## implementation Round 2 — 2026-06-19 17:15 MSK

Scope: verification of the 7 fixes applied in response to implementation
Round 1 (2 🔴 + 5 🟡). Fixes live in the working tree (unstaged), so this
review used `git diff HEAD` and `git diff` (staged vs working) to isolate the
Round 1 → Round 2 delta. All validation re-run from scratch.

Validation run (re-executed this round, not trusted from summary):
 - `uv run ruff check .` → **exit 0** ("All checks passed!") — Round 1 🔴 resolved.
 - `uv run ruff format --check .` → **exit 0** (124 files already formatted).
 - `python3 scripts/grace_check.py` → **exit 0**, 0 errors / 17 warnings.
 - `openspec validate --all --json` → **exit 0**, 29/29 passed (4 change + 25 spec).
 - `uv run pytest -m unit` → **exit 0**, 348 passed, 67 deselected.
 - Smoke import `uv run python -c "from yascheduler.domain import DomainEvent,
   Event, TaskCreated, TaskAllocated, TaskCompleted, TaskFailed,
   TaskAbandoned"` → printed "re-exports OK" (Fix 2 verified end-to-end).
 - `uv run pytest -m integration` → skipped; Docker/testcontainers not
   available in this sandbox (same environment constraint as Round 1, not a
   regression). Re-run before archive.
 - `git diff --name-only` on the frozen artifacts (proposal/design/tasks/specs)
   in the working tree → empty; Round 2 touched NONE of them.

### 🔴 Issues

 - None. Both Round 1 🔴 findings are genuinely resolved (see Strengths for
   concrete evidence).

### 🟡 Suggestions

 - **Dead `new_meta` left in `_record_finalization_event`
   (`yascheduler/application/consume_task.py:179-180`)**. `new_meta =
   task.context.to_metadata(); new_meta.update(dict(meta_add))` is computed
   but never read — the function builds `meta_dict`/`extra_updates` separately
   and the old consumer (`do_task_webhook(task.task_id, new_meta, ...)`) was
   removed by this change. Carried verbatim into the Round 2 extracted helper.
   Minor dead code; drop the two lines or fold into the context update.
   Non-blocking.

 - **`make_daemon: 70 lines with contract` grace warning
   (`yascheduler/di.py`)**. Partially addressed by the `_setup_domain_events`
   extraction (Round 1 reported 79 lines → now 70). Verified via
   `git blame -L 153,181 HEAD -- yascheduler/di.py` that the remaining bulk
   (the cloud-provisioning adapter loop) is commit `d37dc7b9` — i.e. predates
   the domain-events change — so the implementer's "pre-existing, not from
   this change" justification is correct. Further reduction would require
   splitting cloud provisioning, which is out of scope. Acceptable as-is.

 - **No daemon-mode test asserting handler registration**. `test_di.py`
   `TestMakeDaemon` mocks `Orchestrator` and checks kwargs but does not assert
   that 5 webhook handlers are registered on the daemon bus (the symmetric
   CLI assertion `test_no_webhook_handlers_in_cli_mode` does exist). Daemon
   registration is provably intact via `make_daemon → _setup_domain_events()`
   (code-reading confirmed: real `aiohttp.ClientSession`, all 5 event types
   registered with `partial(webhook_handler, http=http)`), so this is a
   coverage gap, not a regression. A symmetric `test_*_handlers_registered`
   would lock the D3/D6 wiring contract. Non-blocking.

### ✅ Strengths

 - **Round 1 🔴 #1 (ruff TC001) RESOLVED.** `yascheduler/domain/model.py:45`
   — `from .events import DomainEvent` now sits inside the existing
   `if TYPE_CHECKING:` block (line 42); `from __future__ import annotations`
   present at line 26, so the annotation-only usage is safe.
   `uv run ruff check .` → exit 0. Full fix, no half-measure.

 - **Round 1 🔴 #2 (`domain/__init__.py` emptied / KG drift) RESOLVED.**
   `yascheduler/domain/__init__.py` restored with full GRACE-lite markup
   (FILE/VERSION 1.7.0, START_MODULE_CONTRACT, START_MODULE_MAP listing all 7
   names, START_CHANGE_SUMMARY with PREVIOUS_CHANGE v1.6.0) and re-exports of
   all 7 public names via `from .events import X as X` (lines 35-41). Smoke
   import succeeded. KG `M-DOMAIN` (knowledge-graph.xml:183-189, purpose
   "re-exports domain events", `<depends>M-DOMAIN-EVENTS</depends>`) +
   `CrossLink` (line 783) now match the code — graph/code drift eliminated.

 - **Round 1 🟡 (UoW shared-list) RESOLVED.**
   `postgres_uow.py:183-191` — `collect_events()` now mutates in place
   (`saved = list(self._saved_tasks); self._saved_tasks.clear();
   for task in saved: ...; self._saved_tasks.append(clean_task)`). Preserves
   the shared list reference handed to `PostgresTaskRepository` at
   `__aenter__`. Order-preserving (iterates `saved` copy in order, `extend`s
   events in order, appends clean tasks in order) → the multi-aggregate
   spec scenario ("Events from multiple aggregates dispatched in one commit")
   remains satisfiable with no event reordering/loss. New test
   `test_collect_events_preserves_shared_list` (test_persistence_adapter.py:148)
   asserts `uow.tasks._saved_tasks is uow._saved_tasks` both before and after
   `collect_events()`.

 - **Round 1 🟡 (webhook signature / CLI wiring) RESOLVED.**
   `webhook.py:63` — strict D4 signature restored
   (`http: aiohttp.ClientSession`, single `event.webhook_url is None`
   early-return; `| None` and `http is None` guard removed).
   `di.py:make_cli_deps` no longer registers any handler (the
   `partial(webhook_handler, http=None)` loop deleted) → CLI dispatch is a
   silent no-op per D3/D6, no dangling `partial`s. Daemon mode unchanged:
   `make_daemon → _setup_domain_events()` still creates a real
   `aiohttp.ClientSession` and registers all 5 event types with
   `partial(webhook_handler, http=http)`, passes `bus` to `PostgresUnitOfWork`
   and `http_session=http` to `Orchestrator`. New test
   `test_no_webhook_handlers_in_cli_mode` (test_di.py:170) asserts the CLI bus
   has no handlers for any of the 5 event types.

 - **Round 1 🟡 (GRACE size limits) RESOLVED (within scope).**
   `consume_task.py` — `_record_finalization_event` extracted
   (sync helper, lines 170-220); `_finalize_task` (lines 237-257) is now well
   under the 60-line limit. Event-recording kwargs preserved verbatim from
   Round 1 (TaskFailed/TaskCompleted with `task_id`, `webhook_url`,
   `webhook_custom_params` from `task.context`, plus `reason` /
   `local_folder`+`has_errors`) — matches D7/D10. Behavior identical; only the
   event-recording block moved into the new helper. `di.py` —
   `_setup_domain_events` extracted (lines 113-124) with full function
   contract. `make_daemon` reduced 79 → 70 lines; remaining length is
   pre-existing cloud code (blame-verified) — see 🟡 above.

 - **Round 1 🟡 (stray files) RESOLVED.** `1.input` and `TESTJOB` are gone
   (`ls` → No such file).

 - **Round 1 🟡 (unstaged AGENTS.md) ACKNOWLEDGED.** `AGENTS.md` test-command
   fix is present in the working tree, intentionally left unstaged per
   git-policy (`git diff --cached` shows 0, `git diff` shows AGENTS.md).
   Acceptable as stated.

 - **CHANGE_SUMMARY entries updated** on webhook.py (v1.1.0), di.py (v4.0.1),
   consume_task.py (v4.0.1), postgres_uow.py (v1.4.1) — each with correct
   PREVIOUS_CHANGE chaining.

 - **No regressions introduced.** Round 1 → Round 2 delta is strictly the 7
   fixes; no incidental edits to use-case kwargs, orchestrator, or event
   construction. D1–D11 all still faithfully implemented; every WHEN/THEN in
   all three spec files remains satisfiable. Knowledge graph accurate (Fix 2
   corrected the sole drift; nothing else moved the graph).

 - **Frozen-artifact integrity holds.** `git diff` (working tree) on
   proposal.md / design.md / tasks.md / specs/*/spec.md is empty — Round 2
   did not modify any frozen artifact. The `M` markers in `git status` are
   staged-only (Round 1 declarative additions from earlier PASS rounds).

### Verdict: PASS
